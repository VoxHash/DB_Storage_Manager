"""
AWS RDS integration — discovery, IAM auth tokens, SSL-aware connection helpers.

Uses boto3 (already a core dependency). Credentials from SecureStore / env /
default AWS credential chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .credentials import require_aws, resolve_cloud_config
from .engines import default_port_for, map_rds_engine, ssl_guidance
from .errors import CloudNotConfiguredError, CloudProviderError, CloudSDKMissingError


def _import_boto3():
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise CloudSDKMissingError(
            "boto3 is required for AWS RDS support. "
            'Install with: pip install boto3  (or pip install -e ".[aws]")'
        ) from exc
    return boto3, ClientError, BotoCoreError


def _session_from_cfg(aws_cfg: Dict[str, Any]):
    boto3, _, _ = _import_boto3()
    kwargs: Dict[str, Any] = {}
    region = aws_cfg.get("region") or "us-east-1"
    if aws_cfg.get("profile"):
        return boto3.Session(profile_name=aws_cfg["profile"], region_name=region)
    if aws_cfg.get("access_key_id") and aws_cfg.get("secret_access_key"):
        kwargs["aws_access_key_id"] = aws_cfg["access_key_id"]
        kwargs["aws_secret_access_key"] = aws_cfg["secret_access_key"]
        if aws_cfg.get("session_token"):
            kwargs["aws_session_token"] = aws_cfg["session_token"]
    return boto3.Session(region_name=region, **kwargs)


class AWSRDSProvider:
    """AWS RDS provider — list instances, IAM tokens, connection profiles."""

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1",
        *,
        session_token: Optional[str] = None,
        profile: Optional[str] = None,
        ssl_ca_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        _import_boto3()
        merged = resolve_cloud_config(
            {
                "aws": {
                    "access_key_id": access_key,
                    "secret_access_key": secret_key,
                    "session_token": session_token,
                    "region": region,
                    "profile": profile,
                    "ssl_ca_path": ssl_ca_path,
                    **(config or {}),
                }
            }
        )
        self.aws_cfg = require_aws(merged)
        self.region = self.aws_cfg.get("region") or region
        self.ssl_ca_path = self.aws_cfg.get("ssl_ca_path")
        self._session = _session_from_cfg(self.aws_cfg)
        self.rds_client = self._session.client("rds")

    def list_databases(self) -> List[Dict[str, Any]]:
        """List RDS DB instances (paginated)."""
        _, ClientError, BotoCoreError = _import_boto3()
        try:
            databases: List[Dict[str, Any]] = []
            paginator = self.rds_client.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    endpoint = db.get("Endpoint") or {}
                    engine = db.get("Engine")
                    databases.append(
                        {
                            "provider": "aws",
                            "id": db["DBInstanceIdentifier"],
                            "engine": engine,
                            "db_type": map_rds_engine(engine),
                            "status": db.get("DBInstanceStatus"),
                            "endpoint": endpoint.get("Address"),
                            "port": endpoint.get("Port"),
                            "database": db.get("DBName"),
                            "size": db.get("AllocatedStorage"),
                            "instance_class": db.get("DBInstanceClass"),
                            "iam_auth": bool(
                                db.get("IAMDatabaseAuthenticationEnabled")
                            ),
                            "storage_encrypted": bool(db.get("StorageEncrypted")),
                            "ssl_guidance": ssl_guidance("aws", map_rds_engine(engine)),
                        }
                    )
            return databases
        except (ClientError, BotoCoreError) as e:
            raise CloudProviderError(f"AWS RDS describe_db_instances failed: {e}") from e

    def get_database_connection_info(
        self, db_instance_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get connection information for a DB instance."""
        _, ClientError, BotoCoreError = _import_boto3()
        try:
            response = self.rds_client.describe_db_instances(
                DBInstanceIdentifier=db_instance_id
            )
            instances = response.get("DBInstances") or []
            if not instances:
                return None
            db = instances[0]
            endpoint = db.get("Endpoint") or {}
            engine = db.get("Engine")
            db_type = map_rds_engine(engine)
            return {
                "provider": "aws",
                "host": endpoint.get("Address"),
                "port": endpoint.get("Port") or default_port_for(db_type),
                "engine": engine,
                "db_type": db_type,
                "database": db.get("DBName"),
                "iam_auth": bool(db.get("IAMDatabaseAuthenticationEnabled")),
                "ssl_ca_path": self.ssl_ca_path,
                "ssl_guidance": ssl_guidance("aws", db_type),
            }
        except (ClientError, BotoCoreError) as e:
            raise CloudProviderError(
                f"AWS RDS describe_db_instances({db_instance_id}) failed: {e}"
            ) from e

    def generate_iam_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
        *,
        region: Optional[str] = None,
    ) -> str:
        """Generate a short-lived RDS IAM authentication token (password substitute)."""
        if not hostname or not username:
            raise CloudNotConfiguredError(
                "RDS IAM auth requires hostname and DB username."
            )
        try:
            return self.rds_client.generate_db_auth_token(
                DBHostname=hostname,
                Port=int(port),
                DBUsername=username,
                Region=region or self.region,
            )
        except Exception as e:
            raise CloudProviderError(
                f"AWS RDS generate_db_auth_token failed: {e}"
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
        """Build a Connections-UI profile dict from a discovered instance."""
        db_type = instance.get("db_type") or map_rds_engine(instance.get("engine"))
        if not db_type:
            raise CloudProviderError(
                f"Unsupported RDS engine for import: {instance.get('engine')}"
            )
        host = instance.get("endpoint") or instance.get("host")
        port = instance.get("port") or default_port_for(db_type)
        use_iam = auth_mode == "iam" or (
            auth_mode == "auto" and instance.get("iam_auth")
        )
        extra: Dict[str, Any] = {
            "cloud_provider": "aws_rds",
            "cloud_instance_id": instance.get("id"),
            "auth_mode": "iam" if use_iam else "password",
            "aws_region": self.region,
            "sslmode": "verify-full" if db_type == "postgresql" else "required",
        }
        if self.ssl_ca_path:
            extra["ssl_ca_path"] = self.ssl_ca_path
        return {
            "id": str(uuid.uuid4()),
            "name": name
            or f"RDS {instance.get('id') or host} ({db_type})",
            "type": db_type,
            "host": host,
            "port": port,
            "database": instance.get("database") or "",
            "username": username or "",
            "password": "" if use_iam else (password or ""),
            "ssh_config": None,
            "extra": extra,
        }

    def get_database_metrics(self, db_instance_id: str) -> Dict[str, Any]:
        """Get CPU utilization from CloudWatch (best-effort)."""
        try:
            cloudwatch = self._session.client("cloudwatch")
            now = datetime.now(timezone.utc)
            cpu_response = cloudwatch.get_metric_statistics(
                Namespace="AWS/RDS",
                MetricName="CPUUtilization",
                Dimensions=[
                    {"Name": "DBInstanceIdentifier", "Value": db_instance_id}
                ],
                StartTime=now - timedelta(hours=1),
                EndTime=now,
                Period=300,
                Statistics=["Average"],
            )
            points = cpu_response.get("Datapoints") or []
            points.sort(key=lambda p: p.get("Timestamp") or now)
            return {
                "cpu_utilization": (
                    points[-1].get("Average", 0) if points else 0
                ),
            }
        except Exception:
            return {}

    def estimate_cost(self, db_instance_id: str) -> Dict[str, Any]:
        """Placeholder cost stub — Pricing API not wired (no invented numbers)."""
        return {
            "monthly_cost": None,
            "currency": "USD",
            "note": "Use AWS Cost Explorer / Pricing API for live estimates.",
            "instance_id": db_instance_id,
        }
