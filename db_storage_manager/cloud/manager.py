"""
Cloud database manager — configure providers from SecureStore/env and discover.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .aws import AWSRDSProvider
from .azure import AzureDatabaseProvider
from .credentials import (
    aws_ready,
    azure_ready,
    configuration_status,
    gcp_ready,
    resolve_cloud_config,
)
from .errors import CloudNotConfiguredError, CloudProviderError, CloudSDKMissingError
from .gcp import GCPCloudSQLProvider


class CloudManager:
    """Cloud database manager for RDS / Cloud SQL / Azure SQL."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = resolve_cloud_config(config)
        self.aws_provider: Optional[AWSRDSProvider] = None
        self.gcp_provider: Optional[GCPCloudSQLProvider] = None
        self.azure_provider: Optional[AzureDatabaseProvider] = None

    @classmethod
    def from_secure_store(
        cls, settings: Optional[Dict[str, Any]] = None
    ) -> "CloudManager":
        return cls(resolve_cloud_config(settings=settings))

    def configure_aws(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1",
        **kwargs: Any,
    ) -> AWSRDSProvider:
        """Configure AWS provider (explicit keys or default chain)."""
        self.aws_provider = AWSRDSProvider(
            access_key, secret_key, region, **kwargs
        )
        return self.aws_provider

    def configure_gcp(
        self, project_id: Optional[str] = None, credentials_path: Optional[str] = None
    ) -> GCPCloudSQLProvider:
        """Configure GCP provider."""
        self.gcp_provider = GCPCloudSQLProvider(project_id, credentials_path)
        return self.gcp_provider

    def configure_azure(
        self,
        subscription_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> AzureDatabaseProvider:
        """Configure Azure provider."""
        self.azure_provider = AzureDatabaseProvider(
            subscription_id, tenant_id, client_id, client_secret
        )
        return self.azure_provider

    def ensure_providers(self) -> Dict[str, str]:
        """Instantiate providers that have credentials. Returns status map."""
        status: Dict[str, str] = {}
        cfg = self._config

        if aws_ready(cfg) and self.aws_provider is None:
            try:
                self.aws_provider = AWSRDSProvider(config=cfg.get("aws"))
                status["aws"] = "ready"
            except (CloudSDKMissingError, CloudNotConfiguredError) as e:
                status["aws"] = str(e)
        elif self.aws_provider is not None:
            status["aws"] = "ready"
        else:
            status["aws"] = "not_configured"

        if gcp_ready(cfg) and self.gcp_provider is None:
            try:
                self.gcp_provider = GCPCloudSQLProvider(config=cfg.get("gcp"))
                status["gcp"] = "ready"
            except (CloudSDKMissingError, CloudNotConfiguredError) as e:
                status["gcp"] = str(e)
        elif self.gcp_provider is not None:
            status["gcp"] = "ready"
        else:
            status["gcp"] = "not_configured"

        if azure_ready(cfg) and self.azure_provider is None:
            try:
                self.azure_provider = AzureDatabaseProvider(config=cfg.get("azure"))
                status["azure"] = "ready"
            except (CloudSDKMissingError, CloudNotConfiguredError) as e:
                status["azure"] = str(e)
        elif self.azure_provider is not None:
            status["azure"] = "ready"
        else:
            status["azure"] = "not_configured"

        return status

    def discover_databases(
        self, *, providers: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Discover databases across configured cloud providers.

        Raises ``CloudNotConfiguredError`` if none are configured.
        Per-provider API failures are recorded as ``{"provider", "error"}``
        entries rather than aborting the whole discovery.
        """
        wanted = {p.lower() for p in (providers or ["aws", "gcp", "azure"])}
        self.ensure_providers()
        databases: List[Dict[str, Any]] = []
        any_ready = False

        if "aws" in wanted and self.aws_provider:
            any_ready = True
            try:
                databases.extend(self.aws_provider.list_databases())
            except (CloudProviderError, CloudSDKMissingError) as e:
                databases.append({"provider": "aws", "error": str(e)})

        if "gcp" in wanted and self.gcp_provider:
            any_ready = True
            try:
                databases.extend(self.gcp_provider.list_databases())
            except (CloudProviderError, CloudSDKMissingError) as e:
                databases.append({"provider": "gcp", "error": str(e)})

        if "azure" in wanted and self.azure_provider:
            any_ready = True
            try:
                databases.extend(self.azure_provider.list_databases())
            except (CloudProviderError, CloudSDKMissingError) as e:
                databases.append({"provider": "azure", "error": str(e)})

        if not any_ready:
            raise CloudNotConfiguredError(
                "No cloud providers configured. Set credentials via "
                ".env.cloud.local / env / SecureStore cloud_managed "
                "(see .env.cloud.local.example), then Discover Cloud again."
            )
        return databases

    def status(self) -> Dict[str, Any]:
        """Configuration readiness without secrets."""
        return configuration_status(self._config)

    def get_cost_optimization_suggestions(self) -> List[Dict[str, Any]]:
        """Reserved for future Cost Explorer / recommender wiring."""
        return []

    def monitor_resources(self) -> Dict[str, Any]:
        """Best-effort metrics when providers are configured."""
        metrics: Dict[str, Any] = {"aws": {}, "gcp": {}, "azure": {}}
        self.ensure_providers()
        if self.aws_provider:
            try:
                for db in self.aws_provider.list_databases():
                    db_id = db.get("id")
                    if db_id and not db.get("error"):
                        metrics["aws"][db_id] = self.aws_provider.get_database_metrics(
                            db_id
                        )
            except Exception as e:
                metrics["aws"]["error"] = str(e)
        return metrics
