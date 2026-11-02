"""Storage analysis SQL + SSH tunnel wiring for Dashboard / Monitoring."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.mysql import MySQLConnection
from db_storage_manager.db.postgres import PostgreSQLConnection
from db_storage_manager.db.session import (
    ensure_tunnel_for_connection,
    tunnel_id_for_connection,
)
from db_storage_manager.monitoring.health import HealthChecker
from db_storage_manager.ssh import reset_shared_tunnel_manager_for_tests


@pytest.fixture(autouse=True)
def _reset_shared_tunnels():
    reset_shared_tunnel_manager_for_tests()
    yield
    reset_shared_tunnel_manager_for_tests()


def test_postgres_analyze_sql_uses_catalog_not_hardcoded_tables():
    src = inspect.getsource(PostgreSQLConnection.analyze_storage)
    assert "clientvault" not in src.lower()
    assert "COUNT(*) FROM" not in src.replace(" ", "")
    assert "pg_catalog.pg_class" in src
    assert "relkind" in src
    assert "pg_total_relation_size(c.oid)" in src
    assert "indexrelid" in src  # via pg_index join, not pg_indexes.indexrelid


def test_mysql_analyze_sql_avoids_statistics_index_length():
    src = inspect.getsource(MySQLConnection.analyze_storage)
    assert "information_schema.STATISTICS" in src
    assert "SUM(index_length)" not in src.lower()
    assert "DATA_LENGTH" in src
    assert "INDEX_LENGTH" in src  # on TABLES only
    assert "TABLE_TYPE = 'BASE TABLE'" in src
    # STATISTICS query must not select INDEX_LENGTH (column does not exist there)
    stats_sql = src.split("information_schema.STATISTICS", 1)[1]
    assert "INDEX_LENGTH" not in stats_sql.split('"""', 1)[0].upper()


def test_ensure_tunnel_rewrites_host_port_and_clears_ssh(monkeypatch):
    fake_tunnel = MagicMock()
    fake_tunnel.is_active.return_value = True
    fake_tunnel.get_local_endpoint.return_value = {"host": "127.0.0.1", "port": 33060}

    manager = MagicMock()
    manager.get_tunnel.return_value = None
    manager.create_tunnel_sync.return_value = fake_tunnel

    connection = {
        "id": "mysql-ssh-1",
        "name": "BrightAds",
        "type": "mysql",
        "host": "10.0.0.5",
        "port": 3306,
        "database": "app",
        "username": "u",
        "password": "p",
        "connection_string": "mysql://remote/app",
        "ssh_config": {
            "enabled": True,
            "ssh_host": "bastion.example.com",
            "ssh_port": 22,
            "ssh_username": "deploy",
            "ssh_password": "secret",
            "remote_host": "127.0.0.1",
            "remote_port": 3306,
        },
    }

    kwargs = ensure_tunnel_for_connection(connection, tunnel_manager=manager)
    manager.create_tunnel_sync.assert_called_once()
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 33060
    assert kwargs["ssh_config"] is None
    assert kwargs["connection_string"] is None
    assert kwargs["database"] == "app"


def test_ensure_tunnel_noop_when_ssh_disabled():
    connection = {
        "id": "pg-1",
        "name": "asesores",
        "type": "postgresql",
        "host": "db.example.supabase.com",
        "port": 6543,
        "database": "postgres",
        "username": "postgres",
        "password": "x",
        "ssh_config": {"enabled": False},
    }
    kwargs = ensure_tunnel_for_connection(connection)
    assert kwargs["host"] == "db.example.supabase.com"
    assert kwargs["port"] == 6543
    assert kwargs.get("ssh_config", {}).get("enabled") is False


def test_tunnel_id_for_connection():
    assert tunnel_id_for_connection({"id": "a", "name": "n"}) == "a"
    assert tunnel_id_for_connection({"name": "n"}) == "n"


def test_postgres_analyze_storage_mocked_catalog():
    cfg = ConnectionConfig(
        id="pg-a",
        name="pg",
        type="postgresql",
        host="localhost",
        port=5432,
        database="postgres",
        username="u",
        password="p",
    )
    conn = PostgreSQLConnection(cfg)
    conn.connected = True

    table_rows = [
        {
            "schema_name": "public",
            "table_name": "orders",
            "total_size": 1000,
            "table_size": 800,
            "row_estimate": 42,
        }
    ]
    index_rows = [
        {"name": "public.orders_pkey", "table_name": "orders", "size": 200}
    ]

    class FakeCursor:
        def __init__(self):
            self._calls = 0

        def execute(self, sql, params=None):
            self._calls += 1
            self._sql = sql

        def fetchall(self):
            if "pg_index" in self._sql or "relkind = 'i'" in self._sql:
                return index_rows
            return table_rows

        def close(self):
            pass

    fake_db = MagicMock()
    fake_db.cursor.return_value = FakeCursor()
    conn.connection = fake_db

    analysis = asyncio.run(conn.analyze_storage())
    assert analysis["tableCount"] == 1
    assert analysis["tables"][0]["name"] == "public.orders"
    assert analysis["tables"][0]["rowCount"] == 42
    assert analysis["indexCount"] == 1
    # Must never have queried a nonexistent hardcoded relation
    assert "clientvault" not in str(fake_db.mock_calls).lower()


def test_mysql_analyze_storage_mocked_information_schema():
    cfg = ConnectionConfig(
        id="my-a",
        name="mysql",
        type="mysql",
        host="127.0.0.1",
        port=3306,
        database="app",
        username="u",
        password="p",
    )
    conn = MySQLConnection(cfg)
    conn.connected = True

    table_rows = [
        {
            "table_schema": "app",
            "table_name": "users",
            "total_size": 500,
            "table_size": 400,
            "index_size": 100,
            "row_count": 10,
        }
    ]
    index_rows = [
        {"index_name": "PRIMARY", "table_name": "users", "seq_in_index": 1},
        {"index_name": "idx_email", "table_name": "users", "seq_in_index": 1},
    ]

    class FakeCursor:
        def __init__(self):
            self._sql = ""

        def execute(self, sql, params=None):
            self._sql = sql
            assert "index_length" not in sql.lower() or "TABLES" in sql.upper()
            if "STATISTICS" in sql.upper():
                assert "INDEX_LENGTH" not in sql.upper()

        def fetchall(self):
            if "STATISTICS" in self._sql.upper():
                return index_rows
            return table_rows

        def close(self):
            pass

    fake_db = MagicMock()
    fake_db.cursor.return_value = FakeCursor()
    conn.connection = fake_db

    analysis = asyncio.run(conn.analyze_storage())
    assert analysis["tableCount"] == 1
    assert analysis["tables"][0]["indexSize"] == 100
    assert analysis["indexCount"] == 2
    assert analysis["indexes"][0]["size"] == 100  # table INDEX_LENGTH on first
    assert analysis["indexes"][1]["size"] == 0


def test_health_checker_keeps_session_and_surfaces_errors():
    cfg = ConnectionConfig(
        id="h1", name="sqlite-health", type="sqlite", database=":memory:"
    )
    from db_storage_manager.db.factory import DatabaseConnectionFactory

    db = DatabaseConnectionFactory.create_connection(cfg)
    asyncio.run(db.connect())
    try:
        checker = HealthChecker(db)
        report = asyncio.run(checker.check_health())
        assert report["status"] in {"healthy", "degraded"}
        assert db.connected is True
        assert "summary" in report
        assert report["checks"]["connectivity"]["status"] == "healthy"
    finally:
        asyncio.run(db.disconnect())


def test_health_checker_unhealthy_summary_on_failure():
    cfg = ConnectionConfig(id="h2", name="broken", type="postgresql")

    class Broken:
        config = cfg
        connected = False

        async def connect(self):
            raise ConnectionRefusedError("Can't connect to MySQL server on 'localhost'")

        async def execute_query(self, query, safe_mode=True):
            raise ConnectionRefusedError("Can't connect to MySQL server on 'localhost'")

    checker = HealthChecker(Broken())  # type: ignore[arg-type]
    report = asyncio.run(checker.check_health())
    assert report["status"] == "unhealthy"
    assert "localhost" in report["summary"] or "Connection" in report["summary"]


def test_analysis_worker_acquires_tunnel_before_analyze():
    from db_storage_manager.gui.dashboard import AnalysisWorker

    connection = {
        "id": "w1",
        "name": "ssh-mysql",
        "type": "mysql",
        "host": "10.0.0.1",
        "port": 3306,
        "database": "app",
        "username": "u",
        "password": "p",
        "ssh_config": {
            "enabled": True,
            "ssh_host": "bastion",
            "ssh_username": "deploy",
            "ssh_password": "x",
            "remote_port": 3306,
        },
    }

    rewritten = {
        "id": "w1",
        "name": "ssh-mysql",
        "type": "mysql",
        "host": "127.0.0.1",
        "port": 3310,
        "database": "app",
        "username": "u",
        "password": "p",
        "ssh_config": None,
        "connection_string": None,
    }

    class FakeDB:
        async def analyze_storage(self):
            return {
                "totalSize": 0,
                "tableCount": 0,
                "indexCount": 0,
                "largestTable": {"name": "N/A", "size": 0, "rowCount": 0},
                "tables": [],
                "indexes": [],
                "lastAnalyzed": "now",
            }

    seen_hosts: List[str] = []

    async def fake_acquire(config):
        seen_hosts.append(config.host)
        return FakeDB()

    async def fake_release(_db):
        return None

    with patch(
        "db_storage_manager.gui.dashboard.ensure_tunnel_for_connection",
        return_value=rewritten,
    ) as ensure:
        with patch(
            "db_storage_manager.gui.dashboard.DatabaseConnectionFactory.acquire",
            side_effect=fake_acquire,
        ):
            with patch(
                "db_storage_manager.gui.dashboard.DatabaseConnectionFactory.release",
                side_effect=fake_release,
            ):
                worker = AnalysisWorker(connection)
                errors: List[str] = []
                results: List[Dict[str, Any]] = []
                worker.error.connect(errors.append)
                worker.finished.connect(results.append)
                worker.run()
                assert errors == []
                assert results
                ensure.assert_called_once_with(connection)
                assert seen_hosts == ["127.0.0.1"]
