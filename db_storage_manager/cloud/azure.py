"""
Azure SQL Database integration — discovery + Entra ID token helpers.

Uses optional ``azure-identity`` + ``azure-mgmt-sql`` (setup extra ``azure``).
"""

from __future__ import annotations

import re
import struct
import uuid
from typing import Any, Dict, List, Optional

from .credentials import require_azure, resolve_cloud_config
from .engines import ssl_guidance
from .errors import CloudProviderError, CloudSDKMissingError

SQL_COPT_SS_ACCESS_TOKEN = 1256
AZURE_SQL_TOKEN_SCOPE = "https://database.windows.net/.default"
_RG_FROM_ID = re.compile(
    r"/resourceGroups/([^/]+)/", re.IGNORECASE
)


def _import_azure():
    try:
        from azure.identity import ClientSecretCredential, DefaultAzureCredential
        from azure.mgmt.sql import SqlManagementClient
    except ImportError as exc:
        raise CloudSDKMissingError(
            "azure-identity and azure-mgmt-sql are required for Azure SQL support. "
            'Install with: pip install -e ".[azure]"'
        ) from exc
    return ClientSecretCredential, DefaultAzureCredential, SqlManagementClient


def resource_group_from_id(resource_id: Optional[str]) -> Optional[str]:
    if not resource_id:
        return None
    match = _RG_FROM_ID.search(resource_id)
    return match.group(1) if match else None


def pack_entra_access_token(token: str) -> bytes:
    """Pack an Entra access token for ODBC SQL_COPT_SS_ACCESS_TOKEN (1256)."""
    token_bytes = token.encode("utf-16-le")
    return struct.pack("<I", len(token_bytes)) + token_bytes


class AzureDatabaseProvider:
    """Azure SQL Database provider."""

    def __init__(
        self,
        subscription_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        *,
        config: Optional[Dict[str, Any]] = None,
    ):
        ClientSecretCredential, DefaultAzureCredential, SqlManagementClient = (
            _import_azure()
        )
        merged = resolve_cloud_config(
            {
                "azure": {
                    "subscription_id": subscription_id,
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    **(config or {}),
                }
            }
        )
        self.azure_cfg = require_azure(merged)
        self.subscription_id = self.azure_cfg["subscription_id"]

        if (
            self.azure_cfg.get("tenant_id")
            and self.azure_cfg.get("client_id")
            and self.azure_cfg.get("client_secret")
        ):
            self._credential = ClientSecretCredential(
                self.azure_cfg["tenant_id"],
                self.azure_cfg["client_id"],
                self.azure_cfg["client_secret"],
            )
        else:
            self._credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False
            )

        self.client = SqlManagementClient(self._credential, self.subscription_id)

    def list_databases(self) -> List[Dict[str, Any]]:
        """List Azure SQL databases across servers in the subscription."""
        try:
            databases: List[Dict[str, Any]] = []
            for server in self.client.servers.list():
                rg = getattr(server, "resource_group", None) or resource_group_from_id(
                    getattr(server, "id", None)
                )
                if not rg:
                    continue
                server_name = server.name
                fqdn = getattr(server, "fully_qualified_domain_name", None) or (
                    f"{server_name}.database.windows.net"
                )
                for db in self.client.databases.list_by_server(rg, server_name):
                    # Skip system "master" noise optionally — keep it for completeness
                    databases.append(
                        {
                            "provider": "azure",
                            "id": db.name,
                            "server": server_name,
                            "resource_group": rg,
                            "status": getattr(db, "status", None),
                            "edition": getattr(db, "edition", None)
                            or getattr(
                                getattr(db, "current_sku", None), "name", None
                            ),
                            "size": getattr(db, "max_size_bytes", None),
                            "endpoint": fqdn,
                            "port": 1433,
                            "database": db.name,
                            "db_type": "sqlserver",
                            "engine": "sqlserver",
                            "ssl_guidance": ssl_guidance("azure", "sqlserver"),
                        }
                    )
            return databases
        except CloudSDKMissingError:
            raise
        except Exception as e:
            raise CloudProviderError(f"Azure SQL list databases failed: {e}") from e

    def get_database_connection_info(
        self, resource_group: str, server_name: str, database_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get connection information for a database."""
        try:
            server = self.client.servers.get(resource_group, server_name)
            fqdn = getattr(server, "fully_qualified_domain_name", None) or (
                f"{server_name}.database.windows.net"
            )
            return {
                "provider": "azure",
                "host": fqdn,
                "port": 1433,
                "database": database_name,
                "engine": "sqlserver",
                "db_type": "sqlserver",
                "resource_group": resource_group,
                "server": server_name,
                "ssl_guidance": ssl_guidance("azure", "sqlserver"),
            }
        except Exception as e:
            raise CloudProviderError(
                f"Azure SQL get server ({server_name}) failed: {e}"
            ) from e

    def get_entra_access_token(self) -> str:
        """Acquire a Microsoft Entra access token for Azure SQL."""
        try:
            token = self._credential.get_token(AZURE_SQL_TOKEN_SCOPE)
            return token.token
        except Exception as e:
            raise CloudProviderError(
                f"Azure Entra token acquisition failed: {e}"
            ) from e

    def get_odbc_access_token_struct(self) -> bytes:
        """Return packed token for pyodbc attrs_before SQL_COPT_SS_ACCESS_TOKEN."""
        return pack_entra_access_token(self.get_entra_access_token())

    def to_connection_profile(
        self,
        instance: Dict[str, Any],
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        auth_mode: str = "entra_token",
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        host = instance.get("endpoint") or instance.get("host")
        database = instance.get("database") or instance.get("id") or ""
        use_entra = auth_mode in ("entra_token", "iam", "aad", "auto")
        extra: Dict[str, Any] = {
            "cloud_provider": "azure_sql",
            "cloud_instance_id": instance.get("id"),
            "resource_group": instance.get("resource_group"),
            "server": instance.get("server"),
            "auth_mode": "entra_token" if use_entra else "password",
            "encrypt": "yes",
            "trust_server_certificate": "no",
        }
        return {
            "id": str(uuid.uuid4()),
            "name": name
            or f"Azure SQL {instance.get('server')}/{database}",
            "type": "sqlserver",
            "host": host,
            "port": int(instance.get("port") or 1433),
            "database": database,
            "username": "" if use_entra else (username or ""),
            "password": "" if use_entra else (password or ""),
            "ssh_config": None,
            "extra": extra,
        }
