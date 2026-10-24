"""Real SQLite driver and factory unit tests (no commercial DB engines)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory
from db_storage_manager.db.sqlite import SQLiteConnection


def _cfg(db_path: Path, *, name: str = "test-sqlite") -> ConnectionConfig:
    return ConnectionConfig(
        id="sqlite-test",
        name=name,
        type="sqlite",
        database=str(db_path),
    )


def test_factory_creates_sqlite(tmp_path: Path):
    conn = DatabaseConnectionFactory.create_connection(_cfg(tmp_path / "f.db"))
    assert isinstance(conn, SQLiteConnection)


def test_factory_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unsupported database type"):
        DatabaseConnectionFactory.create_connection(
            ConnectionConfig(id="x", name="x", type="not-a-real-engine")
        )


def test_factory_sqlite_aliases_and_core_types():
    """Factory maps type strings without requiring live server connections."""
    sqlite = DatabaseConnectionFactory.create_connection(
        ConnectionConfig(id="1", name="s", type="sqlite", database=":memory:")
    )
    assert isinstance(sqlite, SQLiteConnection)

    for db_type in ("postgresql", "postgres", "mysql", "mariadb", "mongodb", "mongo", "redis"):
        cfg = ConnectionConfig(id=db_type, name=db_type, type=db_type, host="127.0.0.1")
        conn = DatabaseConnectionFactory.create_connection(cfg)
        assert conn.config.type == db_type


def test_sqlite_connect_query_schema_backup(tmp_path: Path):
    db_path = tmp_path / "driver.db"
    backup_path = tmp_path / "driver.bak"

    async def run() -> None:
        conn = DatabaseConnectionFactory.create_connection(_cfg(db_path))
        assert await conn.test_connection() is True

        await conn.connect()
        assert conn.connected is True

        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('alpha'), ('beta')",
            safe_mode=False,
        )
        # Durable on-disk state for file-copy backup/restore (aiosqlite needs commit)
        await conn.connection.commit()

        result = await conn.execute_query(
            "SELECT id, name FROM items ORDER BY id",
            safe_mode=True,
        )
        assert result["rowCount"] == 2
        assert result["columns"] == ["id", "name"]
        assert result["rows"] == [
            {"id": 1, "name": "alpha"},
            {"id": 2, "name": "beta"},
        ]
        assert result["executionTime"] >= 0

        schema = await conn.get_schema()
        tables = schema["schemas"][0]["tables"]
        assert len(tables) == 1
        assert tables[0]["name"] == "items"
        col_names = {c["name"] for c in tables[0]["columns"]}
        assert col_names == {"id", "name"}

        analysis = await conn.analyze_storage()
        assert analysis["tableCount"] == 1
        assert analysis["tables"][0]["rowCount"] == 2
        assert analysis["totalSize"] > 0

        backup_meta = await conn.create_backup(str(backup_path))
        assert Path(backup_meta["path"]).exists()
        assert backup_meta["size"] > 0

        backup_conn = DatabaseConnectionFactory.create_connection(
            _cfg(backup_path, name="backup-read")
        )
        await backup_conn.connect()
        from_backup = await backup_conn.execute_query(
            "SELECT COUNT(*) AS n FROM items",
            safe_mode=True,
        )
        assert from_backup["rows"][0]["n"] == 2
        await backup_conn.disconnect()

        await conn.execute_query("DELETE FROM items", safe_mode=False)
        await conn.connection.commit()
        empty = await conn.execute_query("SELECT COUNT(*) AS n FROM items", safe_mode=True)
        assert empty["rows"][0]["n"] == 0

        await conn.restore_backup(str(backup_path))
        restored = await conn.execute_query(
            "SELECT COUNT(*) AS n FROM items",
            safe_mode=True,
        )
        assert restored["rows"][0]["n"] == 2

        await conn.disconnect()
        assert conn.connected is False

    asyncio.run(run())


def test_sqlite_requires_database_path():
    async def run() -> None:
        conn = SQLiteConnection(
            ConnectionConfig(id="bad", name="bad", type="sqlite", database=None)
        )
        with pytest.raises(ValueError, match="database path is required"):
            await conn.connect()

    asyncio.run(run())
