"""
Google Cloud SQL integration
"""

from typing import List, Dict, Any, Optional

try:
    from google.cloud import sqladmin_v1
    from google.oauth2 import service_account

    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False
    sqladmin_v1 = None
    service_account = None


class GCPCloudSQLProvider:
    """Google Cloud SQL provider"""

    def __init__(self, project_id: str, credentials_path: Optional[str] = None):
        if not GCP_AVAILABLE:
            raise ImportError(
                "google-cloud-sqladmin is required for GCP Cloud SQL support. Install it with: pip install google-cloud-sqladmin"
            )
        self.project_id = project_id
        if credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )
            self.client = sqladmin_v1.SqlAdminServiceClient(credentials=credentials)
        else:
            self.client = sqladmin_v1.SqlAdminServiceClient()

    def list_databases(self) -> List[Dict[str, Any]]:
        """List all Cloud SQL instances"""
        try:
            request = sqladmin_v1.ListInstancesRequest(project=self.project_id)
            response = self.client.list_instances(request=request)

            databases = []
            for instance in response.items:
                databases.append(
                    {
                        "id": instance.name,
                        "engine": instance.database_version,
                        "status": instance.state.name,
                        "region": instance.region,
                        "tier": instance.settings.tier,
                    }
                )
            return databases
        except Exception as e:
            print(f"GCP Cloud SQL error: {e}")
            return []

    def get_database_connection_info(
        self, instance_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get connection information for an instance"""
        try:
            request = sqladmin_v1.GetInstanceRequest(
                project=self.project_id,
                instance=instance_id,
            )
            instance = self.client.get_instance(request=request)

            return {
                "host": (
                    instance.ip_addresses[0].ip_address
                    if instance.ip_addresses
                    else None
                ),
                "port": instance.settings.ip_configuration.ipv4_enabled
                and 5432
                or None,
                "engine": instance.database_version,
            }
        except Exception:
            return None
