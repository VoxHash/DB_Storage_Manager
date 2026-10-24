"""Optional engine extras and missing-driver ImportError coverage (no proprietary clients)."""

from __future__ import annotations

from pathlib import Path

import pytest

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory
from db_storage_manager.db import optional_deps
from db_storage_manager.db.optional_deps import OPTIONAL_ENGINES, missing_driver_error


ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = ROOT / "setup.py"


def _cfg(db_type: str) -> ConnectionConfig:
    return ConnectionConfig(
        id=f"{db_type}-test",
        name=db_type,
        type=db_type,
        host="127.0.0.1",
        database="testdb",
        username="user",
        password="pass",
    )


def test_optional_engines_catalog_complete():
    assert set(OPTIONAL_ENGINES) == {"oracle", "mssql", "clickhouse", "influxdb"}
    for engine, (package, hint, note) in OPTIONAL_ENGINES.items():
        assert package
        assert 'pip install -e ".[' in hint
        assert note
        err = missing_driver_error(engine)
        assert isinstance(err, ImportError)
        assert package in str(err)
        assert engine in str(err)
        assert "pip install" in str(err)


def test_setup_extras_declare_current_packages():
    text = SETUP_PY.read_text(encoding="utf-8")
    assert '"oracle": ["oracledb>=2.5.0"]' in text
    assert '"mssql": ["pyodbc>=5.0.0"]' in text
    assert '"clickhouse": ["clickhouse-driver>=0.2.6"]' in text
    assert '"influxdb": ["influxdb-client>=1.38.0"]' in text
    assert "oracledb>=2.5.0" in text
    assert "cx_Oracle" not in text
    # Bundled engines extra includes Oracle now that Thin mode needs no Instant Client
    engines_block_start = text.index('"engines":')
    engines_block = text[engines_block_start : text.index("]", engines_block_start) + 1]
    assert "oracledb" in engines_block
    assert "pyodbc" in engines_block
    assert "clickhouse-driver" in engines_block
    assert "influxdb-client" in engines_block


def test_missing_driver_error_unknown_engine():
    with pytest.raises(ValueError, match="Unknown optional engine"):
        missing_driver_error("not-an-engine")


def test_factory_oracle_missing_driver_message(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.oracle as oracle_mod

    monkeypatch.setattr(oracle_mod, "_oracle_driver", None)
    with pytest.raises(ImportError, match=r"oracledb is required for oracle support") as exc:
        DatabaseConnectionFactory.create_connection(_cfg("oracle"))
    msg = str(exc.value)
    assert '.[oracle]' in msg or "pip install oracledb" in msg
    assert "Instant Client" in msg or "Thin mode" in msg


def test_factory_mssql_missing_driver_message(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.sqlserver as mssql_mod

    monkeypatch.setattr(mssql_mod, "pyodbc", None)
    with pytest.raises(ImportError, match=r"pyodbc is required for mssql support") as exc:
        DatabaseConnectionFactory.create_connection(_cfg("mssql"))
    msg = str(exc.value)
    assert '.[mssql]' in msg or "pip install pyodbc" in msg
    assert "ODBC" in msg


def test_factory_mssql_aliases_missing_driver(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.sqlserver as mssql_mod

    monkeypatch.setattr(mssql_mod, "pyodbc", None)
    for alias in ("sqlserver", "mssql", "sql-server"):
        with pytest.raises(ImportError, match="pyodbc"):
            DatabaseConnectionFactory.create_connection(_cfg(alias))


def test_factory_clickhouse_missing_driver_message(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.clickhouse as ch_mod

    monkeypatch.setattr(ch_mod, "Client", None)
    with pytest.raises(ImportError, match=r"clickhouse-driver is required for clickhouse support") as exc:
        DatabaseConnectionFactory.create_connection(_cfg("clickhouse"))
    assert '.[clickhouse]' in str(exc.value) or "pip install clickhouse-driver" in str(exc.value)


def test_factory_influxdb_missing_driver_message(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.influxdb as influx_mod

    monkeypatch.setattr(influx_mod, "InfluxDBClient", None)
    with pytest.raises(ImportError, match=r"influxdb-client is required for influxdb support") as exc:
        DatabaseConnectionFactory.create_connection(_cfg("influxdb"))
    assert '.[influxdb]' in str(exc.value) or "pip install influxdb-client" in str(exc.value)


def test_sqlserver_pick_driver_prefers_18(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.sqlserver as mssql_mod

    class _FakePyodbc:
        @staticmethod
        def drivers():
            return ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"]

    monkeypatch.setattr(mssql_mod, "pyodbc", _FakePyodbc)
    assert mssql_mod._pick_sql_server_driver() == "ODBC Driver 18 for SQL Server"


def test_sqlserver_pick_driver_none_installed(monkeypatch: pytest.MonkeyPatch):
    import db_storage_manager.db.sqlserver as mssql_mod

    class _FakePyodbc:
        @staticmethod
        def drivers():
            return ["PostgreSQL Unicode"]

    monkeypatch.setattr(mssql_mod, "pyodbc", _FakePyodbc)
    with pytest.raises(ImportError, match="no SQL Server ODBC driver"):
        mssql_mod._pick_sql_server_driver()


def test_optional_deps_module_exported():
    assert optional_deps.OPTIONAL_ENGINES["oracle"][0] == "oracledb"
