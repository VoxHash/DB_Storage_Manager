"""
Azure Database integration
"""

from typing import List, Dict, Any, Optional
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.sql.models import Database


class AzureDatabaseProvider:
    """Azure Database provider"""

    def __init__(self, subscription_id: str, tenant_id: Optional[str] = None, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.subscription_id = subscription_id
        
        if tenant_id and client_id and client_secret:
            credentials = ClientSecretCredential(tenant_id, client_id, client_secret)
        else:
            credentials = DefaultAzureCredential()
        
        self.client = SqlManagementClient(credentials, subscription_id)

    def list_databases(self) -> List[Dict[str, Any]]:
        """List all Azure SQL databases"""
        try:
            databases = []
            for server in self.client.servers.list():
                for db in self.client.databases.list_by_server(server.resource_group_name, server.name):
                    databases.append({
                        "id": db.name,
                        "server": server.name,
                        "resource_group": server.resource_group_name,
                        "status": db.status,
                        "edition": db.edition,
                        "size": db.max_size_bytes,
                    })
            return databases
        except Exception as e:
            print(f"Azure Database error: {e}")
            return []

    def get_database_connection_info(self, resource_group: str, server_name: str, database_name: str) -> Optional[Dict[str, Any]]:
        """Get connection information for a database"""
        try:
            server = self.client.servers.get(resource_group, server_name)
            return {
                "host": f"{server_name}.database.windows.net",
                "port": 1433,
                "database": database_name,
                "engine": "sqlserver",
            }
        except Exception:
            return None

