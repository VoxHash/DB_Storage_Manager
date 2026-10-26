"""
Google Cloud SQL integration — discovery + connection helpers.

Discovery prefers ``google-cloud-sql`` (``google.cloud.sqladmin_v1``) when
installed, otherwise falls back to ``googleapiclient`` (already a core
dependency). Optional ``cloud-sql-python-connector`` is documented for
IAM/TLS connections.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from .credentials import require_gcp, resolve_cloud_config
from .engines import default_port_for, map_cloudsql_version, ssl_guidance
from .errors import CloudProviderError, CloudSDKMissingError


def _service_account_credentials(credentials_path: Optional[str]):
    if not credentials_path:
        return None
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise CloudSDKMissingError(
            "google-auth is required for GCP service-account files. "
            "Install with: pip install google-auth"
        ) from exc
    return service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _build_sqladmin_client(credentials_path: Optional[str]) -> Tuple[Any, str]:
    """Return (client, backend) where backend is 'sqladmin_v1' or 'discovery'."""
    credentials = _service_account_credentials(credentials_path)

    try:
        from google.cloud import sqladmin_v1

        if credentials is not None:
            client = sqladmin_v1.SqlAdminServiceClient(credentials=credentials)
        else:
            client = sqladmin_v1.SqlAdminServiceClient()
        return client, "sqladmin_v1"
    except ImportError:
        pass

    try:
        from googleapiclient import discovery
        from google.auth import default as google_auth_default
    except ImportError as exc:
        raise CloudSDKMissingError(
            "Cloud SQL discovery requires google-cloud-sql or "
            "google-api-python-client. Install with: "
            'pip install -e ".[gcp]"  (or pip install google-cloud-sql)'
        ) from exc

    if credentials is None:
        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    service = discovery.build(
        "sqladmin", "v1", credentials=credentials, cache_discovery=False
    )
    return service, "discovery"


class GCPCloudSQLProvider:
    """Google Cloud SQL provider."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        *,
        config: Optional[Dict[str, Any]] = None,
    ):
        merged = resolve_cloud_config(
            {
                "gcp": {
                    "project_id": project_id,
                    "credentials_path": credentials_path,
                    **(config or {}),
                }
            }
        )
        self.gcp_cfg = require_gcp(merged)
        self.project_id = self.gcp_cfg["project_id"]
        self.credentials_path = self.gcp_cfg.get("credentials_path")
        self.client, self._backend = _build_sqladmin_client(self.credentials_path)

    def list_databases(self) -> List[Dict[str, Any]]:
        """List Cloud SQL instances in the project."""
        try:
            if self._backend == "sqladmin_v1":
                from google.cloud import sqladmin_v1

                request = sqladmin_v1.ListInstancesRequest(project=self.project_id)
                response = self.client.list_instances(request=request)
                # Gapic clients return a pager; also accept .items for stubs
                if hasattr(response, "items") and not callable(
                    getattr(response, "__iter__", None)
                ):
                    items = list(response.items or [])
                else:
                    items = list(response)
            else:
                resp = (
                    self.client.instances()
                    .list(project=self.project_id)
                    .execute()
                )
                items = resp.get("items") or []

            databases: List[Dict[str, Any]] = []
            for instance in items:
                databases.append(self._normalize_instance(instance))
            return databases
        except CloudSDKMissingError:
            raise
        except Exception as e:
            raise CloudProviderError(f"GCP Cloud SQL list instances failed: {e}") from e

    def _normalize_instance(self, instance: Any) -> Dict[str, Any]:
        if hasattr(instance, "name"):
            name = instance.name
            version = getattr(instance, "database_version", None)
            state = getattr(instance, "state", None)
            state_name = getattr(state, "name", None) if state is not None else None
            region = getattr(instance, "region", None)
            settings = getattr(instance, "settings", None)
            tier = getattr(settings, "tier", None) if settings else None
            ip_addresses = list(getattr(instance, "ip_addresses", []) or [])
            connection_name = getattr(instance, "connection_name", None)
            primary_ip = None
            for ip in ip_addresses:
                ip_addr = getattr(ip, "ip_address", None)
                ip_type = str(getattr(ip, "type_", getattr(ip, "type", "")) or "")
                if "PRIMARY" in ip_type.upper() or primary_ip is None:
                    primary_ip = ip_addr
        else:
            name = instance.get("name")
            version = instance.get("databaseVersion")
            state_name = instance.get("state")
            region = instance.get("region")
            settings = instance.get("settings") or {}
            tier = settings.get("tier")
            ip_addresses = instance.get("ipAddresses") or []
            connection_name = instance.get("connectionName")
            primary_ip = None
            for ip in ip_addresses:
                if ip.get("type") == "PRIMARY" or primary_ip is None:
                    primary_ip = ip.get("ipAddress")

        db_type = map_cloudsql_version(str(version) if version else None)
        return {
            "provider": "gcp",
            "id": name,
            "engine": version,
            "db_type": db_type,
            "status": state_name,
            "region": region,
            "tier": tier,
            "endpoint": primary_ip,
            "port": default_port_for(db_type),
            "connection_name": connection_name
            or (f"{self.project_id}:{region}:{name}" if name and region else None),
            "project_id": self.project_id,
            "ssl_guidance": ssl_guidance("gcp", db_type),
        }

    def get_database_connection_info(
        self, instance_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get connection information for an instance."""
        try:
            if self._backend == "sqladmin_v1":
                from google.cloud import sqladmin_v1

                request = sqladmin_v1.GetInstanceRequest(
                    project=self.project_id,
                    instance=instance_id,
                )
                instance = self.client.get_instance(request=request)
            else:
                instance = (
                    self.client.instances()
                    .get(project=self.project_id, instance=instance_id)
                    .execute()
                )
            info = self._normalize_instance(instance)
            return {
                "provider": "gcp",
                "host": info.get("endpoint"),
                "port": info.get("port"),
                "engine": info.get("engine"),
                "db_type": info.get("db_type"),
                "connection_name": info.get("connection_name"),
                "project_id": self.project_id,
                "ssl_guidance": info.get("ssl_guidance"),
            }
        except Exception as e:
            raise CloudProviderError(
                f"GCP Cloud SQL get instance ({instance_id}) failed: {e}"
            ) from e

    def to_connection_profile(
        self,
        instance: Dict[str, Any],
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        auth_mode: str = "password",
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        db_type = instance.get("db_type") or map_cloudsql_version(
            str(instance.get("engine") or "")
        )
        if not db_type:
            raise CloudProviderError(
                f"Unsupported Cloud SQL engine for import: {instance.get('engine')}"
            )
        host = instance.get("endpoint") or instance.get("host")
        port = instance.get("port") or default_port_for(db_type)
        extra: Dict[str, Any] = {
            "cloud_provider": "gcp_cloudsql",
            "cloud_instance_id": instance.get("id"),
            "connection_name": instance.get("connection_name"),
            "project_id": instance.get("project_id") or self.project_id,
            "auth_mode": auth_mode if auth_mode in ("password", "iam") else "password",
            "sslmode": "require",
        }
        return {
            "id": str(uuid.uuid4()),
            "name": name
            or f"Cloud SQL {instance.get('id') or host} ({db_type})",
            "type": db_type,
            "host": host,
            "port": port,
            "database": instance.get("database") or "",
            "username": username or "",
            "password": password or "",
            "ssh_config": None,
            "extra": extra,
        }
