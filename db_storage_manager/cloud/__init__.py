"""
Cloud-managed database integrations (AWS RDS, GCP Cloud SQL, Azure SQL).
"""

from .aws import AWSRDSProvider
from .azure import AzureDatabaseProvider
from .connect_auth import cloud_auth_mode, cloud_provider, resolve_password_and_ssl
from .credentials import (
    configuration_status,
    load_cloud_dotenv,
    resolve_cloud_config,
)
from .errors import CloudNotConfiguredError, CloudProviderError, CloudSDKMissingError
from .gcp import GCPCloudSQLProvider
from .manager import CloudManager

__all__ = [
    "AWSRDSProvider",
    "GCPCloudSQLProvider",
    "AzureDatabaseProvider",
    "CloudManager",
    "CloudNotConfiguredError",
    "CloudProviderError",
    "CloudSDKMissingError",
    "configuration_status",
    "load_cloud_dotenv",
    "resolve_cloud_config",
    "resolve_password_and_ssl",
    "cloud_auth_mode",
    "cloud_provider",
]
