"""PITR Verify, the first premium plugin.

Catalog and provider decisions are checked against the shapes PostgreSQL,
RDS, Aurora, Cloud SQL, Azure Database for PostgreSQL, Supabase and Neon
actually return. A live PostgreSQL server (the same ``DSM_LIVE_PG_*``
variables as ``tests/test_live_restore.py``) is required for the catalog
query itself; that part skips when no server is configured.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.factory import DatabaseConnectionFactory
from db_storage_manager.plugins.licensing import PluginLicenseRequired
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.marketplace import LocalPluginMarketplace
from db_storage_manager.plugins.pricing import (
    PREMIUM_PRODUCT_IDS,
    PRICING_TIERS,
    accepted_product_ids,
)
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import (
    PermissionDenied,
    UserRole,
    get_auth_manager,
    reset_auth_manager,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = bundled_plugin_dir("pitr-verify")


def _plugin_module():
    path = PLUGIN_DIR / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        "pitr_verify_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pitr():
    return _plugin_module()


def test_manifest_points_at_the_provisioned_monthly_product():
    manifest = load_manifest(PLUGIN_DIR)
    monthly = PREMIUM_PRODUCT_IDS["pitr-verify"]["monthly"]
    assert manifest.license is not None
    assert manifest.license.product_id == monthly
    assert (
        manifest.license.pricing["monthly"]
        == PRICING_TIERS["plugin"]["monthly"]
    )
    assert (
        manifest.license.pricing["yearly"] == PRICING_TIERS["plugin"]["yearly"]
    )
    assert (
        manifest.license.pricing["one_time"]
        == PRICING_TIERS["plugin"]["one_time"]
    )
    assert monthly in accepted_product_ids(monthly)
    assert PREMIUM_PRODUCT_IDS["bundle"]["yearly"] in accepted_product_ids(
        monthly
    )


def test_plugin_loads_and_dry_run_lists_licensechain_bodies():
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    assert plugin.metadata.plugin_id == "pitr-verify"
    assert plugin.initialize({}) is True
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "licensechain_products.py"),
            str(PLUGIN_DIR),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "dry run" in completed.stderr
    assert "1.99" in completed.stdout
    assert "--apply" not in completed.args


def test_catalog_off_matches_a_stock_postgres(pitr):
    """archive_mode=off / wal_level=replica is what a stock server reports."""
    report = pitr.interpret_catalog(
        [
            {"name": "archive_mode", "setting": "off"},
            {"name": "archive_command", "setting": "(disabled)"},
            {"name": "wal_level", "setting": "replica"},
            {"name": "archive_timeout", "setting": "0"},
            {"name": "server_version_num", "setting": "160000"},
        ],
        {
            "archived_count": 0,
            "last_archived_wal": None,
            "last_archived_time": None,
            "failed_count": 0,
            "last_failed_wal": None,
            "last_failed_time": None,
            "stats_reset": None,
        },
    )
    assert report["status"] == "fail"
    assert report["pitr_enabled"] is False
    assert report["source"] == "pg_stat_archiver"
    assert report["retention_days"] is None
    assert report["retention_matches"] is None
    assert "pg_stat_archiver" in pitr._ARCHIVER_SQL
    assert "pg_settings" in pitr._SETTINGS_SQL


def test_catalog_does_not_invent_a_retention_window(pitr):
    report = pitr.interpret_catalog(
        [
            {"name": "archive_mode", "setting": "on"},
            {
                "name": "archive_command",
                "setting": "test ! -f /mnt/wal/%f && cp %p /mnt/wal/%f",
            },
            {"name": "wal_level", "setting": "replica"},
        ],
        {
            "archived_count": 4,
            "last_archived_wal": "00000001000000000000000A",
            "last_archived_time": "2026-11-03T12:00:00+00:00",
            "failed_count": 1,
            "last_failed_wal": "000000010000000000000001",
            "last_failed_time": "2026-11-01T00:00:00+00:00",
            "stats_reset": None,
        },
        expected_retention_days=7,
    )
    assert report["pitr_enabled"] is True
    assert report["status"] == "not_available"
    assert report["retention_matches"] is None
    assert "retention" in (report["reason"] or "").lower()


def test_catalog_failing_archiver_is_not_healthy(pitr):
    report = pitr.interpret_catalog(
        [
            {"name": "archive_mode", "setting": "on"},
            {"name": "archive_command", "setting": "cp %p /mnt/wal/%f"},
            {"name": "wal_level", "setting": "logical"},
        ],
        {
            "archived_count": 2,
            "last_archived_wal": "000000010000000000000003",
            "last_archived_time": "2026-11-02T00:00:00+00:00",
            "failed_count": 5,
            "last_failed_wal": "000000010000000000000004",
            "last_failed_time": "2026-11-03T00:00:00+00:00",
            "stats_reset": None,
        },
    )
    assert report["pitr_enabled"] is True
    assert report["status"] == "fail"


def test_rds_postgres_retention_is_backup_retention_period(pitr):
    # DescribeDBInstances DBInstance: BackupRetentionPeriod + LatestRestorableTime.
    # https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DBInstance.html
    report = pitr.interpret_rds_instance(
        {
            "Engine": "postgres",
            "BackupRetentionPeriod": 7,
            "LatestRestorableTime": "2026-11-03T12:00:00Z",
        },
        expected_retention_days=7,
    )
    assert report["status"] == "ok"
    assert report["pitr_enabled"] is True
    assert report["retention_days"] == 7
    assert report["retention_matches"] is True
    assert report["window_days"] is None
    assert report["latest_restorable_time"].startswith("2026-11-03")

    disabled = pitr.interpret_rds_instance(
        {"Engine": "postgres", "BackupRetentionPeriod": 0},
        expected_retention_days=7,
    )
    assert disabled["status"] == "fail"
    assert disabled["pitr_enabled"] is False
    assert disabled["retention_matches"] is False

    missing = pitr.interpret_rds_instance({"Engine": "postgres"})
    assert missing["status"] == "not_available"
    assert missing["pitr_enabled"] is None


def test_aurora_window_comes_from_the_cluster(pitr):
    # DescribeDBClusters: EarliestRestorableTime and BackupRetentionPeriod.
    report = pitr.interpret_rds_cluster(
        {
            "Engine": "aurora-postgresql",
            "BackupRetentionPeriod": 7,
            "EarliestRestorableTime": "2026-10-27T12:00:00Z",
            "LatestRestorableTime": "2026-11-03T12:00:00Z",
        },
        expected_retention_days=7,
    )
    assert report["status"] == "ok"
    assert report["source"] == "aws_aurora"
    assert report["window_days"] == pytest.approx(7.0)
    assert report["retention_matches"] is True

    unknown = pitr.interpret_rds_cluster(
        {
            "Engine": "aurora-postgresql",
            "BackupRetentionPeriod": 7,
            "LatestRestorableTime": "2026-11-03T12:00:00Z",
        }
    )
    assert unknown["status"] == "not_available"
    assert unknown["pitr_enabled"] is None


def test_cloudsql_uses_point_in_time_recovery_enabled(pitr):
    # https://docs.cloud.google.com/sql/docs/postgres/admin-api/rest/v1/instances
    report = pitr.interpret_cloudsql(
        {
            "databaseVersion": "POSTGRES_16",
            "settings": {
                "backupConfiguration": {
                    "pointInTimeRecoveryEnabled": True,
                    "transactionLogRetentionDays": 7,
                    "backupRetentionSettings": {
                        "retentionUnit": "COUNT",
                        "retainedBackups": 8,
                    },
                }
            },
        },
        expected_retention_days=7,
    )
    assert report["status"] == "ok"
    assert report["retention_days"] == 7
    mismatch = pitr.interpret_cloudsql(
        {
            "databaseVersion": "POSTGRES_16",
            "settings": {
                "backupConfiguration": {
                    "pointInTimeRecoveryEnabled": True,
                    "transactionLogRetentionDays": 7,
                }
            },
        },
        expected_retention_days=14,
    )
    assert mismatch["status"] == "fail"
    assert mismatch["retention_matches"] is False
    absent = pitr.interpret_cloudsql(
        {
            "databaseVersion": "POSTGRES_16",
            "settings": {"backupConfiguration": {}},
        }
    )
    assert absent["pitr_enabled"] is None
    assert absent["status"] == "not_available"


def test_azure_flexible_server_backup_window(pitr):
    # https://learn.microsoft.com/en-us/rest/api/postgresql/servers/get
    earliest = "2025-06-01T18:35:22.123456Z"
    now = datetime(2025, 6, 8, 18, 35, 22, tzinfo=timezone.utc)
    report = pitr.interpret_azure_flexible(
        {
            "properties": {
                "backup": {
                    "backupRetentionDays": 7,
                    "earliestRestoreDate": earliest,
                    "geoRedundantBackup": "Enabled",
                }
            }
        },
        expected_retention_days=7,
        now=now,
    )
    assert report["status"] == "ok"
    assert report["pitr_enabled"] is True
    assert report["retention_days"] == 7
    assert report["window_days"] == pytest.approx(7.0, abs=0.01)
    hidden = pitr.interpret_azure_flexible({"properties": {}})
    assert hidden["status"] == "not_available"
    assert hidden["pitr_enabled"] is None


def test_supabase_reports_enabled_without_inventing_addon_days(pitr):
    # GET /v1/projects/{ref}/database/backups — pitr_enabled, no retention days.
    # https://supabase.com/docs/reference/api/v1-list-all-backups
    start = datetime(2026, 10, 27, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    report = pitr.interpret_supabase(
        {
            "region": "us-east-1",
            "walg_enabled": True,
            "pitr_enabled": True,
            "backups": [],
            "physical_backup_data": {
                "earliest_physical_backup_date_unix": int(start.timestamp()),
                "latest_physical_backup_date_unix": int(end.timestamp()),
            },
        },
        expected_retention_days=7,
    )
    assert report["pitr_enabled"] is True
    assert report["retention_days"] is None
    assert report["status"] == "not_available"
    assert report["window_days"] == pytest.approx(7.0)
    off = pitr.interpret_supabase(
        {"pitr_enabled": False, "walg_enabled": False}
    )
    assert off["status"] == "fail"
    assert off["pitr_enabled"] is False


def test_neon_history_retention_seconds(pitr):
    # GET /api/v2/projects/{id} history_retention_seconds.
    # https://neon.com/docs/introduction/history-window
    week = pitr.interpret_neon(
        {
            "project": {
                "id": "noisy-recipe-12345678",
                "history_retention_seconds": 604800,
            }
        },
        expected_retention_days=7,
    )
    assert week["status"] == "ok"
    assert week["retention_days"] == pytest.approx(7.0)
    assert week["retention_matches"] is True
    six_hours = pitr.interpret_neon(
        {"project": {"history_retention_seconds": 21600}},
        expected_retention_days=0.25,
    )
    assert six_hours["status"] == "ok"
    disabled = pitr.interpret_neon(
        {"project": {"history_retention_seconds": 0}},
        expected_retention_days=0,
    )
    assert disabled["status"] == "ok"
    assert disabled["pitr_enabled"] is False
    missing = pitr.interpret_neon({"project": {"id": "noisy-recipe-12345678"}})
    assert missing["status"] == "not_available"
    assert missing["pitr_enabled"] is None


def test_unknown_provider_is_not_guessed(pitr, monkeypatch):
    monkeypatch.delenv("DSM_SUPABASE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN", raising=False)
    unknown = pitr.fetch_provider(
        {"cloud_provider": "digitalocean", "cloud_instance_id": "db-1"},
        expected_retention_days=7,
    )
    assert unknown["status"] == "not_available"
    assert unknown["pitr_enabled"] is None
    supabase = pitr.fetch_provider(
        {
            "cloud_provider": "supabase",
            "cloud_instance_id": "abcdefghijklmnop",
        },
        expected_retention_days=None,
    )
    assert supabase["status"] == "not_available"
    assert "token" in (supabase["reason"] or "").lower()
    azure_sql = pitr.fetch_provider(
        {"cloud_provider": "azure_sql", "cloud_instance_id": "server"},
        expected_retention_days=7,
    )
    assert azure_sql["pitr_enabled"] is None
    assert "SQL Server" in azure_sql["reason"]


def test_sqlite_connection_is_not_available(isolated_secure_store, tmp_path):
    reset_auth_manager()
    db_path = tmp_path / "pitr.db"
    connection = DatabaseConnectionFactory.create_connection(
        ConnectionConfig(
            id="pitr-sqlite",
            name="pitr-sqlite",
            type="sqlite",
            database=str(db_path),
        )
    )
    asyncio.run(connection.connect())
    try:
        plugin = load_plugin_from_directory(PLUGIN_DIR)
        report = plugin.execute(connection, expected_retention_days=7)
    finally:
        asyncio.run(connection.disconnect())
    assert report["status"] == "not_available"
    assert report["engine"] == "sqlite"
    assert report["pitr_enabled"] is None
    assert "sqlite" in report["reason"]


def test_mysql_type_does_not_open_a_connection(isolated_secure_store):
    reset_auth_manager()

    class _ConfigOnly:
        def __init__(self):
            self.config = ConnectionConfig(
                id="pitr-mysql",
                name="pitr-mysql",
                type="mysql",
                host="127.0.0.1",
                port=1,
                database="dsm",
                username="nobody",
                password="secret",
            )
            self.connected = False

        def connect(self):
            raise AssertionError("mysql PITR check must not connect")

    plugin = load_plugin_from_directory(PLUGIN_DIR)
    report = plugin.execute(_ConfigOnly())
    assert report["status"] == "not_available"
    assert report["engine"] == "mysql"
    assert report["pitr_enabled"] is None


def test_guest_cannot_run_and_viewer_can(isolated_secure_store):
    reset_auth_manager()
    auth = get_auth_manager()
    auth.bootstrap_admin("pitr-admin", "password1")
    auth.authenticate("pitr-admin", "password1")
    auth.create_user("pitr-guest", "password1", role=UserRole.GUEST)
    auth.create_user("pitr-viewer", "password1", role=UserRole.VIEWER)
    auth.logout()
    auth.authenticate("pitr-guest", "password1")

    class _Boom:
        config = ConnectionConfig(
            id="boom", name="boom", type="sqlite", database=":memory:"
        )

        def connect(self):
            raise AssertionError("permission check must run before any query")

    plugin = load_plugin_from_directory(PLUGIN_DIR)
    with pytest.raises(PermissionDenied) as denied:
        plugin.execute(_Boom())
    assert denied.value.permission == "monitoring:read"

    auth.logout()
    auth.authenticate("pitr-viewer", "password1")
    report = plugin.execute(_Boom())
    assert report["status"] == "not_available"
    assert report["permission"] == "monitoring:read"


def test_install_requires_a_license(
    isolated_secure_store, tmp_path, monkeypatch
):
    store, data_dir = isolated_secure_store
    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir()
    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "PLUGINS_DIR", plugins_dir)
    market = LocalPluginMarketplace(plugins_dir=plugins_dir)
    with pytest.raises(PluginLicenseRequired):
        market.install_from_path(PLUGIN_DIR)
    assert not (plugins_dir / "installed" / "pitr-verify").exists()
    assert store.get_plugin_licenses() == {}


def _live_pg():
    host = os.environ.get("DSM_LIVE_PG_HOST")
    user = os.environ.get("DSM_LIVE_PG_USER")
    if not host or not user:
        return None
    return {
        "host": host,
        "port": int(os.environ["DSM_LIVE_PG_PORT"]),
        "user": user,
        "password": os.environ.get("DSM_LIVE_PG_PASSWORD", ""),
    }


def test_live_postgres_catalog(isolated_secure_store):
    env = _live_pg()
    if env is None:
        pytest.skip("DSM_LIVE_PG_* is not set")
    reset_auth_manager()
    connection = DatabaseConnectionFactory.create_connection(
        ConnectionConfig(
            id="pitr-live",
            name="pitr-live",
            type="postgresql",
            host=env["host"],
            port=env["port"],
            database="postgres",
            username=env["user"],
            password=env["password"],
        )
    )
    asyncio.run(connection.connect())
    try:
        plugin = load_plugin_from_directory(PLUGIN_DIR)
        report = plugin.execute(connection)
    finally:
        asyncio.run(connection.disconnect())

    assert report["engine"] == "postgresql"
    assert report["source"] == "pg_stat_archiver"
    assert report["status"] in ("ok", "fail")
    assert isinstance(report["pitr_enabled"], bool)
    catalog = report["catalog"]
    assert "archive_mode" in catalog["settings"]
    assert "wal_level" in catalog["settings"]
    assert "archived_count" in catalog["archiver"]
    if catalog["settings"]["archive_mode"] == "off":
        assert report["pitr_enabled"] is False
        assert report["status"] == "fail"
        assert report["retention_days"] is None


def test_live_postgres_without_pg_monitor_is_not_available(
    isolated_secure_store,
):
    """A role that cannot read pg_stat_archiver must not be reported as PITR off."""
    env = _live_pg()
    if env is None:
        pytest.skip("DSM_LIVE_PG_* is not set")
    import psycopg2
    from psycopg2.extensions import TRANSACTION_STATUS_IDLE

    reset_auth_manager()
    role = "dsm_pitr_nopriv"
    password = "dsm-pitr-nopriv"
    admin = psycopg2.connect(
        host=env["host"],
        port=env["port"],
        user=env["user"],
        password=env["password"],
        dbname="postgres",
    )
    admin.autocommit = True
    original_acl = None
    changed = False
    try:
        cur = admin.cursor()
        cur.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        if not cur.fetchone()[0]:
            pytest.skip("DSM_LIVE_PG_USER is not a superuser")
        cur.execute(
            "SELECT relacl::text FROM pg_class "
            "WHERE oid = 'pg_catalog.pg_stat_archiver'::regclass"
        )
        original_acl = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone():
            cur.execute(
                f'REVOKE ALL PRIVILEGES ON DATABASE postgres FROM "{role}"'
            )
            cur.execute(f'DROP ROLE IF EXISTS "{role}"')
        cur.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD %s', (password,))
        cur.execute(f'GRANT CONNECT ON DATABASE postgres TO "{role}"')
        cur.execute("REVOKE ALL ON pg_catalog.pg_stat_archiver FROM PUBLIC")
        cur.execute(f'REVOKE ALL ON pg_catalog.pg_stat_archiver FROM "{role}"')
        changed = True

        limited = DatabaseConnectionFactory.create_connection(
            ConnectionConfig(
                id="pitr-limited",
                name="pitr-limited",
                type="postgresql",
                host=env["host"],
                port=env["port"],
                database="postgres",
                username=role,
                password=password,
            )
        )
        asyncio.run(limited.connect())
        try:
            raw = limited.connection
            assert raw.get_transaction_status() == TRANSACTION_STATUS_IDLE
            plugin = load_plugin_from_directory(PLUGIN_DIR)
            report = plugin.execute(limited)
        finally:
            asyncio.run(limited.disconnect())
    finally:
        cur = admin.cursor()
        if changed:
            if original_acl is None:
                cur.execute(
                    "UPDATE pg_class SET relacl = NULL "
                    "WHERE oid = 'pg_catalog.pg_stat_archiver'::regclass"
                )
            else:
                cur.execute(
                    "UPDATE pg_class SET relacl = %s::aclitem[] "
                    "WHERE oid = 'pg_catalog.pg_stat_archiver'::regclass",
                    (original_acl,),
                )
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone():
            cur.execute(
                f'REVOKE ALL PRIVILEGES ON DATABASE postgres FROM "{role}"'
            )
            cur.execute(f'DROP ROLE IF EXISTS "{role}"')
        admin.close()

    assert report["status"] == "not_available"
    assert report["pitr_enabled"] is None
    assert "not available on this role" in (report["reason"] or "").lower()
