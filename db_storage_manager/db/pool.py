"""
Connection pooling for long-lived SQL engine sessions.

Reusable checkout / return of ``DatabaseConnection`` instances keyed by
connection profile. Non-SQL engines are still acquired through the same API
but are not retained in the idle pool (released connections are disconnected).
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
)

from .base import ConnectionConfig, DatabaseConnection

SQL_ENGINE_TYPES = frozenset(
    {
        "postgresql",
        "postgres",
        "mysql",
        "mariadb",
        "sqlite",
        "oracle",
        "sqlserver",
        "mssql",
        "sql-server",
    }
)


class PoolClosedError(RuntimeError):
    """Raised when the pool has been shut down."""


class PoolExhaustedError(RuntimeError):
    """Raised when max_size_per_key idle+in-use connections are already out."""


def is_sql_engine(db_type: str) -> bool:
    """Return True when ``db_type`` is a pooled SQL engine."""
    return (db_type or "").lower() in SQL_ENGINE_TYPES


def pool_key_for(config: ConnectionConfig) -> str:
    """Stable pool key for a connection profile."""
    db_type = (config.type or "").lower()
    if config.id:
        return f"{db_type}:{config.id}"
    parts = [
        db_type,
        config.host or "",
        str(config.port or ""),
        config.database or "",
        config.username or "",
        config.connection_string or "",
    ]
    return ":".join(parts)


class SQLEnginePool:
    """
    Thread-safe pool of long-lived SQL ``DatabaseConnection`` sessions.

    Checkout returns a connected session; release returns it to the idle list
    without disconnecting (SQL engines only). ``close()`` disconnects every
    idle session and rejects further checkouts; in-use sessions are
    disconnected when released after close.
    """

    def __init__(
        self,
        max_size_per_key: int = 4,
        factory: Optional[Callable[[ConnectionConfig], DatabaseConnection]] = None,
    ) -> None:
        if max_size_per_key < 1:
            raise ValueError("max_size_per_key must be >= 1")
        if factory is None:
            from .factory import DatabaseConnectionFactory

            factory = DatabaseConnectionFactory.create_connection
        self._factory = factory
        self._max_size = max_size_per_key
        self._idle: Dict[str, List[DatabaseConnection]] = {}
        self._in_use: Dict[int, str] = {}
        self._unpooled: Set[int] = set()
        self._created: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def max_size_per_key(self) -> int:
        return self._max_size

    def stats(self, key: Optional[str] = None) -> Dict[str, Any]:
        """Return idle / in-use / created counts (optionally for one key)."""
        with self._lock:
            if key is not None:
                idle = len(self._idle.get(key, []))
                in_use = sum(1 for k in self._in_use.values() if k == key)
                return {
                    "key": key,
                    "idle": idle,
                    "in_use": in_use,
                    "created": self._created.get(key, 0),
                    "max_size": self._max_size,
                }
            return {
                "keys": sorted(set(self._idle) | set(self._created)),
                "idle_total": sum(len(v) for v in self._idle.values()),
                "in_use_total": len(self._in_use),
                "created": dict(self._created),
                "closed": self._closed,
            }

    async def checkout(self, config: ConnectionConfig) -> DatabaseConnection:
        """Acquire a connected session for ``config`` (pooled for SQL engines)."""
        with self._lock:
            if self._closed:
                raise PoolClosedError("SQL engine pool is closed")

        if not is_sql_engine(config.type):
            conn = self._factory(config)
            await conn.connect()
            with self._lock:
                if self._closed:
                    await self._safe_disconnect(conn)
                    raise PoolClosedError("SQL engine pool is closed")
                self._unpooled.add(id(conn))
            return conn

        key = pool_key_for(config)
        conn: Optional[DatabaseConnection] = None
        create_new = False

        with self._lock:
            if self._closed:
                raise PoolClosedError("SQL engine pool is closed")
            idle = self._idle.setdefault(key, [])
            if idle:
                conn = idle.pop()
                self._in_use[id(conn)] = key
            else:
                created = self._created.get(key, 0)
                if created >= self._max_size:
                    raise PoolExhaustedError(
                        f"Connection pool exhausted for {key} "
                        f"(max_size_per_key={self._max_size})"
                    )
                create_new = True
                self._created[key] = created + 1

        if create_new:
            conn = self._factory(config)
            try:
                await conn.connect()
            except Exception:
                with self._lock:
                    self._created[key] = max(0, self._created.get(key, 1) - 1)
                raise
            with self._lock:
                if self._closed:
                    await self._safe_disconnect(conn)
                    self._created[key] = max(0, self._created.get(key, 1) - 1)
                    raise PoolClosedError("SQL engine pool is closed")
                self._in_use[id(conn)] = key
            return conn

        assert conn is not None
        try:
            await self._ensure_ready(conn, config)
        except Exception:
            with self._lock:
                self._in_use.pop(id(conn), None)
                self._created[key] = max(0, self._created.get(key, 1) - 1)
            await self._safe_disconnect(conn)
            raise
        return conn

    async def _ensure_ready(
        self, conn: DatabaseConnection, config: ConnectionConfig
    ) -> None:
        """Reconnect when needed (e.g. aiosqlite bound to a different event loop)."""
        db_type = (config.type or "").lower()
        if db_type == "sqlite":
            raw = getattr(conn, "connection", None)
            need_reconnect = not getattr(conn, "connected", False) or raw is None
            if not need_reconnect:
                try:
                    loop = asyncio.get_running_loop()
                    bound = getattr(raw, "_loop", None)
                    if bound is not None and bound is not loop:
                        need_reconnect = True
                except RuntimeError:
                    need_reconnect = True
            if need_reconnect:
                if getattr(conn, "connected", False) or raw is not None:
                    await self._safe_disconnect(conn)
                await conn.connect()
            return
        if not getattr(conn, "connected", False):
            await conn.connect()

    async def release(self, conn: DatabaseConnection) -> None:
        """Return a session to the pool (or disconnect if unpooled / closed)."""
        if conn is None:
            return
        conn_id = id(conn)

        with self._lock:
            if conn_id in self._unpooled:
                self._unpooled.discard(conn_id)
                should_disconnect = True
                key = None
            elif conn_id in self._in_use:
                key = self._in_use.pop(conn_id)
                should_disconnect = self._closed
            else:
                # Unknown / already released — disconnect to avoid leaks
                should_disconnect = True
                key = None

        if should_disconnect or key is None:
            await self._safe_disconnect(conn)
            if key is not None:
                with self._lock:
                    self._created[key] = max(0, self._created.get(key, 1) - 1)
            return

        # Keep SQL session open for reuse
        with self._lock:
            if self._closed:
                await self._safe_disconnect(conn)
                self._created[key] = max(0, self._created.get(key, 1) - 1)
                return
            self._idle.setdefault(key, []).append(conn)

    async def discard_key(self, connection_id: str) -> None:
        """Disconnect and drop all idle sessions for a connection profile id."""
        suffix = f":{connection_id}"
        to_close: List[DatabaseConnection] = []
        with self._lock:
            matching = [k for k in list(self._idle.keys()) if k.endswith(suffix)]
            for key in matching:
                idle_list = self._idle.pop(key, [])
                to_close.extend(idle_list)
                self._created[key] = max(
                    0, self._created.get(key, 0) - len(idle_list)
                )
        for conn in to_close:
            await self._safe_disconnect(conn)

    async def close(self) -> None:
        """Shut down the pool: reject new checkouts and disconnect idle sessions."""
        to_close: List[DatabaseConnection] = []
        with self._lock:
            self._closed = True
            for key, idle_list in list(self._idle.items()):
                to_close.extend(idle_list)
                self._created[key] = max(
                    0, self._created.get(key, 0) - len(idle_list)
                )
            self._idle.clear()
        for conn in to_close:
            await self._safe_disconnect(conn)

    @asynccontextmanager
    async def connection(
        self, config: ConnectionConfig
    ) -> AsyncIterator[DatabaseConnection]:
        """Checkout a session for the duration of the ``async with`` block."""
        conn = await self.checkout(config)
        try:
            yield conn
        finally:
            await self.release(conn)

    @staticmethod
    async def _safe_disconnect(conn: DatabaseConnection) -> None:
        try:
            await conn.disconnect()
        except Exception:
            pass


_pool_lock = threading.Lock()
_default_pool: Optional[SQLEnginePool] = None


def get_sql_engine_pool() -> SQLEnginePool:
    """Return the process-wide SQL engine pool (created on first use)."""
    global _default_pool
    with _pool_lock:
        if _default_pool is None or _default_pool.closed:
            _default_pool = SQLEnginePool()
        return _default_pool


async def shutdown_sql_engine_pool() -> None:
    """Close the process-wide pool if it exists."""
    global _default_pool
    with _pool_lock:
        pool = _default_pool
        _default_pool = None
    if pool is not None:
        await pool.close()


def reset_sql_engine_pool_for_tests() -> None:
    """Synchronously drop the singleton (tests only; does not await disconnect)."""
    global _default_pool
    with _pool_lock:
        _default_pool = None


def close_sql_engine_pool_blocking() -> None:
    """Close the global pool from a synchronous shutdown path."""
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(shutdown_sql_engine_pool())
        finally:
            loop.close()
    except Exception:
        reset_sql_engine_pool_for_tests()
