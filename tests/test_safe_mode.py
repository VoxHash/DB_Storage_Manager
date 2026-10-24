"""Safe Mode enforcement against a real SQLite connection."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory


def _sqlite(tmp_path: Path):
    cfg = ConnectionConfig(
        id="safe-mode",
        name="safe-mode-sqlite",
        type="sqlite",
        database=str(tmp_path / "safe.db"),
    )
    return DatabaseConnectionFactory.create_connection(cfg)


@pytest.mark.parametrize(
    "blocked_sql",
    [
        "INSERT INTO items(name) VALUES ('nope')",
        "UPDATE items SET name = 'x'",
        "DELETE FROM items",
        "DROP TABLE items",
        "CREATE TABLE other (id INTEGER)",
        "  insert into items(name) values ('spaced')",
    ],
)
def test_safe_mode_blocks_non_select(tmp_path: Path, blocked_sql: str):
    async def run() -> None:
        conn = _sqlite(tmp_path)
        await conn.connect()
        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('seed')",
            safe_mode=False,
        )

        with pytest.raises(ValueError, match="Only SELECT queries are allowed in safe mode"):
            await conn.execute_query(blocked_sql, safe_mode=True)

        still = await conn.execute_query("SELECT COUNT(*) AS n FROM items", safe_mode=True)
        assert still["rows"][0]["n"] == 1
        await conn.disconnect()

    asyncio.run(run())


def test_safe_mode_allows_select(tmp_path: Path):
    async def run() -> None:
        conn = _sqlite(tmp_path)
        await conn.connect()
        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('ok')",
            safe_mode=False,
        )

        result = await conn.execute_query(
            "SELECT name FROM items WHERE name = 'ok'",
            safe_mode=True,
        )
        assert result["rowCount"] == 1
        assert result["rows"][0]["name"] == "ok"

        # Leading whitespace + lowercase still counts as SELECT
        result2 = await conn.execute_query(
            "  select id from items",
            safe_mode=True,
        )
        assert result2["rowCount"] == 1
        await conn.disconnect()

    asyncio.run(run())


def test_safe_mode_off_allows_writes(tmp_path: Path):
    async def run() -> None:
        conn = _sqlite(tmp_path)
        await conn.connect()
        await conn.execute_query(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
            safe_mode=False,
        )
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('written')",
            safe_mode=False,
        )
        result = await conn.execute_query("SELECT name FROM items", safe_mode=True)
        assert result["rows"][0]["name"] == "written"
        await conn.disconnect()

    asyncio.run(run())
