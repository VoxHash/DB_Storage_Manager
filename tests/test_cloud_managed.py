"""Cloud-managed DB integrations — unit tests at SDK boundaries (no live cloud)."""

from __future__ import annotations

import struct
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from db_storage_manager.cloud.aws import AWSRDSProvider
from db_storage_manager.cloud.azure import (
    AzureDatabaseProvider,
    pack_entra_access_token,
    resource_group_from_id,
)
from db_storage_manager.cloud.connect_auth import resolve_password_and_ssl
from db_storage_manager.cloud.credentials import (
    aws_ready,
    azure_ready,
    configuration_status,
    gcp_ready,
    resolve_cloud_config,
)
from db_storage_manager.cloud.engines import (
    map_cloudsql_version,
    map_rds_engine,
    ssl_guidance,
)
from db_storage_manager.cloud.errors import (
    CloudNotConfiguredError,
    CloudProviderError,
    CloudSDKMissingError,
)
from db_storage_manager.cloud.gcp import GCPCloudSQLProvider
from db_storage_manager.cloud.manager import CloudManager
from db_storage_manager.db.base import ConnectionConfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = ROOT / "setup.py"


def test_setup_extras_declare_cloud_packages():
    text = SETUP_PY.read_text(encoding="utf-8")
    assert '"aws":' in text
    assert '"gcp":' in text
    assert '"azure":' in text
    assert '"cloud":' in text
    assert "google-cloud-sql" in text
    assert "azure-mgmt-sql" in text
    assert "azure-identity" in text


def test_engine_maps():
    assert map_rds_engine("postgres") == "postgresql"
    assert map_rds_engine("aurora-mysql") == "mysql"
    assert map_rds_engine("sqlserver-ex") == "sqlserver"
    assert map_cloudsql_version("POSTGRES_15") == "postgresql"
    assert map_cloudsql_version("MYSQL_8_0") == "mysql"
    assert map_cloudsql_version("SQLSERVER_2019_STANDARD") == "sqlserver"
    assert "RDS" in ssl_guidance("aws")
    assert "Auth Proxy" in ssl_guidance("gcp")
    assert "Entra" in ssl_guidance("azure")


def test_resolve_cloud_config_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSM_AWS_REGION", "eu-west-1")
    monkeypatch.setenv("DSM_AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setenv("DSM_AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("DSM_GCP_PROJECT_ID", "proj-1")
    monkeypatch.setenv("DSM_AZURE_SUBSCRIPTION_ID", "sub-1")
    cfg = resolve_cloud_config({}, settings={}, load_env_file=False)
    assert cfg["aws"]["region"] == "eu-west-1"
    assert cfg["aws"]["access_key_id"] == "AKIATEST"
    assert cfg["gcp"]["project_id"] == "proj-1"
    assert cfg["azure"]["subscription_id"] == "sub-1"
    assert aws_ready(cfg) and gcp_ready(cfg) and azure_ready(cfg)
    status = configuration_status({}, settings={})
    # reload may pick dotenv; force from our cfg shape
    assert "aws" in status


def test_resolve_cloud_config_secure_store_overrides_defaults(
    monkeypatch: pytest.MonkeyPatch,
):
    for key in (
        "DSM_AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "DSM_GCP_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "DSM_AZURE_SUBSCRIPTION_ID",
        "AZURE_SUBSCRIPTION_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = resolve_cloud_config(
        settings={
            "cloud_managed": {
                "aws": {"region": "ap-southeast-2"},
                "gcp": {"project_id": "store-proj"},
                "azure": {"subscription_id": "store-sub"},
            }
        },
        load_env_file=False,
    )
    assert cfg["aws"]["region"] == "ap-southeast-2"
    assert cfg["gcp"]["project_id"] == "store-proj"
    assert cfg["azure"]["subscription_id"] == "store-sub"


def test_aws_list_databases_mocked(monkeypatch: pytest.MonkeyPatch):
    fake_page = {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "app-db",
                "Engine": "postgres",
                "DBInstanceStatus": "available",
                "Endpoint": {"Address": "app-db.xxxx.us-east-1.rds.amazonaws.com", "Port": 5432},
                "DBName": "app",
                "AllocatedStorage": 20,
                "DBInstanceClass": "db.t3.micro",
                "IAMDatabaseAuthenticationEnabled": True,
                "StorageEncrypted": True,
            }
        ]
    }

    class FakePaginator:
        def paginate(self):
            yield fake_page

    fake_client = MagicMock()
    fake_client.get_paginator.return_value = FakePaginator()
    fake_session = MagicMock()
    fake_session.client.return_value = fake_client

    monkeypatch.setattr(
        "db_storage_manager.cloud.aws._session_from_cfg", lambda cfg: fake_session
    )
    monkeypatch.setattr(
        "db_storage_manager.cloud.aws._import_boto3",
        lambda: (MagicMock(), Exception, Exception),
    )

    provider = AWSRDSProvider(
        access_key="AKIA",
        secret_key="secret",
        region="us-east-1",
    )
    # bypass require path by injecting
    provider.rds_client = fake_client
    provider.region = "us-east-1"
    provider.ssl_ca_path = None
    dbs = provider.list_databases()
    assert len(dbs) == 1
    assert dbs[0]["id"] == "app-db"
    assert dbs[0]["db_type"] == "postgresql"
    assert dbs[0]["iam_auth"] is True

    profile = provider.to_connection_profile(dbs[0], auth_mode="iam", username="dbuser")
    assert profile["type"] == "postgresql"
    assert profile["extra"]["auth_mode"] == "iam"
    assert profile["extra"]["cloud_provider"] == "aws_rds"
    assert profile["password"] == ""


def test_aws_iam_token_mocked(monkeypatch: pytest.MonkeyPatch):
    fake_client = MagicMock()
    fake_client.generate_db_auth_token.return_value = "iam-token-xyz"

    monkeypatch.setattr(
        "db_storage_manager.cloud.aws._import_boto3",
        lambda: (MagicMock(), Exception, Exception),
    )
    monkeypatch.setattr(
        "db_storage_manager.cloud.aws._session_from_cfg",
        lambda cfg: MagicMock(client=MagicMock(return_value=fake_client)),
    )

    provider = object.__new__(AWSRDSProvider)
    provider.rds_client = fake_client
    provider.region = "us-east-1"
    provider.ssl_ca_path = "/tmp/ca.pem"
    provider.aws_cfg = {"region": "us-east-1"}

    token = provider.generate_iam_auth_token("host.rds.amazonaws.com", 5432, "jane")
    assert token == "iam-token-xyz"
    fake_client.generate_db_auth_token.assert_called_once()


def test_resolve_password_rds_iam(monkeypatch: pytest.MonkeyPatch):
    class FakeProvider:
        def __init__(self, *a, **k):
            pass

        def generate_iam_auth_token(self, host, port, user, region=None):
            return f"token-for-{user}@{host}:{port}"

    monkeypatch.setattr("db_storage_manager.cloud.aws.AWSRDSProvider", FakeProvider)
    cfg = ConnectionConfig(
        id="1",
        name="rds",
        type="postgresql",
        host="db.example.rds.amazonaws.com",
        port=5432,
        database="app",
        username="iam_user",
        password="",
        extra={
            "cloud_provider": "aws_rds",
            "auth_mode": "iam",
            "aws_region": "us-east-1",
            "ssl_ca_path": "/ca.pem",
        },
    )
    password, ssl_kwargs = resolve_password_and_ssl(cfg)
    assert password.startswith("token-for-iam_user@")
    assert ssl_kwargs["sslmode"] == "verify-full"
    assert ssl_kwargs["sslrootcert"] == "/ca.pem"


def test_resolve_password_gcp_iam_guides():
    cfg = ConnectionConfig(
        id="1",
        name="gcp",
        type="postgresql",
        host="1.2.3.4",
        port=5432,
        database="app",
        username="user",
        extra={
            "cloud_provider": "gcp_cloudsql",
            "auth_mode": "iam",
            "connection_name": "p:r:i",
        },
    )
    with pytest.raises(CloudNotConfiguredError, match="Auth Proxy"):
        resolve_password_and_ssl(cfg)


def test_gcp_list_via_discovery_mock(monkeypatch: pytest.MonkeyPatch):
    fake_service = MagicMock()
    fake_service.instances().list().execute.return_value = {
        "items": [
            {
                "name": "pg-prod",
                "databaseVersion": "POSTGRES_14",
                "state": "RUNNABLE",
                "region": "us-central1",
                "settings": {"tier": "db-custom-1-3840"},
                "ipAddresses": [{"type": "PRIMARY", "ipAddress": "10.0.0.1"}],
                "connectionName": "proj:us-central1:pg-prod",
            }
        ]
    }

    monkeypatch.setattr(
        "db_storage_manager.cloud.gcp._build_sqladmin_client",
        lambda path: (fake_service, "discovery"),
    )

    provider = object.__new__(GCPCloudSQLProvider)
    provider.project_id = "proj"
    provider.credentials_path = None
    provider.client = fake_service
    provider._backend = "discovery"
    provider.gcp_cfg = {"project_id": "proj"}

    dbs = provider.list_databases()
    assert dbs[0]["db_type"] == "postgresql"
    assert dbs[0]["endpoint"] == "10.0.0.1"
    profile = provider.to_connection_profile(dbs[0])
    assert profile["extra"]["cloud_provider"] == "gcp_cloudsql"
    assert profile["extra"]["connection_name"] == "proj:us-central1:pg-prod"


def test_azure_resource_group_and_token_pack():
    rg = resource_group_from_id(
        "/subscriptions/sub/resourceGroups/rg-sql/providers/Microsoft.Sql/servers/s1"
    )
    assert rg == "rg-sql"
    packed = pack_entra_access_token("abc")
    length = struct.unpack("<I", packed[:4])[0]
    assert length == len("abc".encode("utf-16-le"))
    assert packed[4:] == "abc".encode("utf-16-le")


def test_azure_list_mocked(monkeypatch: pytest.MonkeyPatch):
    server = MagicMock()
    server.name = "myserver"
    server.id = (
        "/subscriptions/sub/resourceGroups/rg1/providers/Microsoft.Sql/servers/myserver"
    )
    server.fully_qualified_domain_name = "myserver.database.windows.net"

    db = MagicMock()
    db.name = "appdb"
    db.status = "Online"
    db.edition = "Basic"
    db.max_size_bytes = 1024
    db.current_sku = None

    fake_client = MagicMock()
    fake_client.servers.list.return_value = [server]
    fake_client.databases.list_by_server.return_value = [db]

    monkeypatch.setattr(
        "db_storage_manager.cloud.azure._import_azure",
        lambda: (MagicMock(), MagicMock(), MagicMock),
    )

    provider = object.__new__(AzureDatabaseProvider)
    provider.client = fake_client
    provider.subscription_id = "sub"
    provider.azure_cfg = {"subscription_id": "sub"}
    provider._credential = MagicMock()

    dbs = provider.list_databases()
    assert dbs[0]["database"] == "appdb"
    assert dbs[0]["endpoint"] == "myserver.database.windows.net"
    profile = provider.to_connection_profile(dbs[0], auth_mode="entra_token")
    assert profile["type"] == "sqlserver"
    assert profile["extra"]["auth_mode"] == "entra_token"


def test_azure_entra_token_on_connect_auth(monkeypatch: pytest.MonkeyPatch):
    class FakeAzure:
        def __init__(self, *a, **k):
            pass

        def get_odbc_access_token_struct(self):
            return pack_entra_access_token("tok")

    monkeypatch.setattr(
        "db_storage_manager.cloud.azure.AzureDatabaseProvider", FakeAzure
    )
    cfg = ConnectionConfig(
        id="1",
        name="az",
        type="sqlserver",
        host="s.database.windows.net",
        port=1433,
        database="db",
        extra={"cloud_provider": "azure_sql", "auth_mode": "entra_token"},
    )
    password, ssl_kwargs = resolve_password_and_ssl(cfg)
    assert password is None
    assert 1256 in ssl_kwargs["odbc_attrs_before"]


def test_cloud_manager_not_configured(monkeypatch: pytest.MonkeyPatch):
    for key in list(__import__("os").environ):
        if key.startswith(("DSM_AWS", "DSM_GCP", "DSM_AZURE", "AWS_", "GOOGLE_", "AZURE_", "GCLOUD_")):
            monkeypatch.delenv(key, raising=False)
    mgr = CloudManager({"aws": {}, "gcp": {}, "azure": {}})
    # Force empty config
    mgr._config = {"aws": {}, "gcp": {}, "azure": {}}
    with pytest.raises(CloudNotConfiguredError):
        mgr.discover_databases()


def test_cloud_manager_discover_with_fake_aws(monkeypatch: pytest.MonkeyPatch):
    class FakeAWS:
        def list_databases(self) -> List[Dict[str, Any]]:
            return [
                {
                    "provider": "aws",
                    "id": "x",
                    "db_type": "postgresql",
                    "endpoint": "h",
                    "port": 5432,
                }
            ]

    mgr = CloudManager({"aws": {"region": "us-east-1"}, "gcp": {}, "azure": {}})
    mgr.aws_provider = FakeAWS()
    mgr.gcp_provider = None
    mgr.azure_provider = None
    monkeypatch.setattr(mgr, "ensure_providers", lambda: {"aws": "ready"})
    found = mgr.discover_databases(providers=["aws"])
    assert found[0]["id"] == "x"


def test_env_cloud_example_exists():
    example = ROOT / ".env.cloud.local.example"
    assert example.is_file()
    text = example.read_text(encoding="utf-8")
    assert "DSM_AWS_REGION" in text
    assert "DSM_GCP_PROJECT_ID" in text
    assert "DSM_AZURE_SUBSCRIPTION_ID" in text
    assert "Never commit" in text


@pytest.mark.skipif(
    not (
        __import__("os").environ.get("DSM_AWS_ACCESS_KEY_ID")
        and __import__("os").environ.get("DSM_LIVE_CLOUD") == "1"
    ),
    reason="Live AWS RDS probe skipped (set DSM_LIVE_CLOUD=1 + AWS creds)",
)
def test_live_aws_rds_list():
    provider = AWSRDSProvider()
    dbs = provider.list_databases()
    assert isinstance(dbs, list)


def test_cloud_sdk_missing_message():
    err = CloudSDKMissingError("missing sdk")
    assert isinstance(err, ImportError)
    with pytest.raises(CloudProviderError):
        raise CloudProviderError("api failed")
