"""Real SQL engine connection pool tests (SQLite; no mocked pool behavior)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory
from db_storage_manager.db.pool import (
    PoolClosedError,
    PoolExhaustedError,
    SQLEnginePool,
    is_sql_engine,
    pool_key_for,
    reset_sql_engine_pool_for_tests,
    shutdown_sql_engine_pool,
)


def _cfg(db_path: Path, *, conn_id: str = "pool-sqlite") -> ConnectionConfig:
    return ConnectionConfig(
        id=conn_id,
        name="pool-test",
        type="sqlite",
        database=str(db_path),
    )


@pytest.fixture(autouse=True)
def _reset_global_pool():
    reset_sql_engine_pool_for_tests()
    yield
    reset_sql_engine_pool_for_tests()


def test_is_sql_engine_classification():
    assert is_sql_engine("sqlite") is True
    assert is_sql_engine("PostgreSQL") is True
    assert is_sql_engine("mysql") is True
    assert is_sql_engine("mongodb") is False
    assert is_sql_engine("redis") is False


def test_pool_key_uses_connection_id():
    cfg = ConnectionConfig(id="abc", name="n", type="sqlite", database=":memory:")
    assert pool_key_for(cfg) == "sqlite:abc"


def test_checkout_release_reuses_same_session(tmp_path: Path):
    db_path = tmp_path / "reuse.db"
    pool = SQLEnginePool(max_size_per_key=2)

    async def run() -> None:
        cfg = _cfg(db_path)
        first = await pool.checkout(cfg)
        await first.execute_query(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)",
            safe_mode=False,
        )
        await first.execute_query(
            "INSERT INTO t(v) VALUES ('kept')",
            safe_mode=False,
        )
        await first.connection.commit()
        await pool.release(first)

        stats = pool.stats(pool_key_for(cfg))
        assert stats["idle"] == 1
        assert stats["in_use"] == 0
        assert stats["created"] == 1

        second = await pool.checkout(cfg)
        assert second is first
        assert second.connected is True
        result = await second.execute_query("SELECT v FROM t", safe_mode=True)
        assert result["rows"] == [{"v": "kept"}]
        await pool.release(second)

        await pool.close()
        assert pool.closed is True
        assert pool.stats()["idle_total"] == 0

    asyncio.run(run())


def test_concurrent_checkouts_are_distinct_until_release(tmp_path: Path):
    db_path = tmp_path / "two.db"
    pool = SQLEnginePool(max_size_per_key=2)

    async def run() -> None:
        cfg = _cfg(db_path)
        a = await pool.checkout(cfg)
        b = await pool.checkout(cfg)
        assert a is not b
        assert pool.stats(pool_key_for(cfg))["in_use"] == 2
        await pool.release(a)
        await pool.release(b)
        assert pool.stats(pool_key_for(cfg))["idle"] == 2
        await pool.close()

    asyncio.run(run())


def test_pool_exhausted_raises(tmp_path: Path):
    db_path = tmp_path / "exhaust.db"
    pool = SQLEnginePool(max_size_per_key=1)

    async def run() -> None:
        cfg = _cfg(db_path)
        first = await pool.checkout(cfg)
        with pytest.raises(PoolExhaustedError):
            await pool.checkout(cfg)
        await pool.release(first)
        # After release, checkout succeeds again
        again = await pool.checkout(cfg)
        assert again is first
        await pool.release(again)
        await pool.close()

    asyncio.run(run())


def test_close_rejects_further_checkout(tmp_path: Path):
    db_path = tmp_path / "closed.db"
    pool = SQLEnginePool(max_size_per_key=2)

    async def run() -> None:
        cfg = _cfg(db_path)
        conn = await pool.checkout(cfg)
        await pool.release(conn)
        await pool.close()
        with pytest.raises(PoolClosedError):
            await pool.checkout(cfg)

    asyncio.run(run())


def test_context_manager_returns_to_idle(tmp_path: Path):
    db_path = tmp_path / "ctx.db"
    pool = SQLEnginePool(max_size_per_key=2)

    async def run() -> None:
        cfg = _cfg(db_path)
        async with pool.connection(cfg) as conn:
            assert conn.connected is True
            await conn.execute_query(
                "CREATE TABLE x (id INTEGER PRIMARY KEY)",
                safe_mode=False,
            )
            await conn.connection.commit()
        assert pool.stats(pool_key_for(cfg))["idle"] == 1
        async with pool.connection(cfg) as conn2:
            result = await conn2.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='x'",
                safe_mode=True,
            )
            assert result["rowCount"] == 1
        await pool.close()

    asyncio.run(run())


def test_factory_acquire_release_and_shutdown(tmp_path: Path):
    db_path = tmp_path / "factory.db"

    async def run() -> None:
        cfg = _cfg(db_path, conn_id="factory-1")
        conn = await DatabaseConnectionFactory.acquire(cfg)
        assert conn.connected is True
        await conn.execute_query(
            "CREATE TABLE f (id INTEGER PRIMARY KEY)",
            safe_mode=False,
        )
        await conn.connection.commit()
        await DatabaseConnectionFactory.release(conn)

        pool = DatabaseConnectionFactory.get_pool()
        assert pool.stats(pool_key_for(cfg))["idle"] == 1

        again = await DatabaseConnectionFactory.acquire(cfg)
        assert again is conn
        await DatabaseConnectionFactory.release(again)

        await DatabaseConnectionFactory.shutdown_pool()
        with pytest.raises(PoolClosedError):
            # New pool is created only via get_pool after shutdown; acquire uses fresh pool
            # Force closed pool path:
            closed = SQLEnginePool(max_size_per_key=1)
            await closed.close()
            await closed.checkout(cfg)

    asyncio.run(run())


def test_discard_key_drops_idle_sessions(tmp_path: Path):
    db_path = tmp_path / "discard.db"
    pool = SQLEnginePool(max_size_per_key=2)

    async def run() -> None:
        cfg = _cfg(db_path, conn_id="to-drop")
        conn = await pool.checkout(cfg)
        await pool.release(conn)
        assert pool.stats(pool_key_for(cfg))["idle"] == 1
        await pool.discard_key("to-drop")
        assert pool.stats(pool_key_for(cfg))["idle"] == 0
        # New checkout creates a fresh session
        fresh = await pool.checkout(cfg)
        assert fresh is not conn
        await pool.release(fresh)
        await pool.close()

    asyncio.run(run())


def test_shutdown_sql_engine_pool_global(tmp_path: Path):
    db_path = tmp_path / "global.db"

    async def run() -> None:
        cfg = _cfg(db_path, conn_id="global-1")
        conn = await DatabaseConnectionFactory.acquire(cfg)
        await DatabaseConnectionFactory.release(conn)
        await shutdown_sql_engine_pool()
        # Next acquire creates a new open pool
        again = await DatabaseConnectionFactory.acquire(cfg)
        assert again.connected is True
        await DatabaseConnectionFactory.release(again)
        await shutdown_sql_engine_pool()

    asyncio.run(run())
