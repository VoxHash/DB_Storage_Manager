"""Pooler health — direct versus pooled PostgreSQL.

The operator passes the connections they already saved. The plugin times
``SELECT 1``, reads ``max_connections`` and ``pg_stat_activity``, and asks
``SHOW pool_mode`` (PgBouncer / some Supavisor builds). A server that rejects
``SHOW pool_mode`` is reported as pool mode not available. It does not invent
a pooled host, open a port that was not given, or store credentials.

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
``license.product_id`` is ``PREMIUM_PRODUCT_IDS["pooler-health"]["monthly"]``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "pooler-health"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"

_HEADROOM_SQL = """
SELECT current_setting('max_connections') AS max_connections,
       (SELECT count(*) FROM pg_stat_activity) AS active
"""
_PING_SQL = "SELECT 1"
_POOL_MODE_SQL = "SHOW pool_mode"


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Pooler health",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Compare a direct PostgreSQL connection with a pooled one: "
            "latency, pool mode, and max_connections headroom"
        ),
        plugin_type=PluginType.PERFORMANCE_MONITORING,
        plugin_id=PLUGIN_ID,
    )


def _engine_name(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    raw = getattr(config, "type", None) if config is not None else None
    if raw is None and isinstance(connection, dict):
        raw = connection.get("type")
    if raw is None:
        return None
    name = str(raw).strip().lower()
    if name in {"postgres", "supabase"}:
        return "postgresql"
    return name


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def assess(direct: Dict[str, Any], pooled: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare two probe dicts. ``pooled`` None means the caller did not supply one."""

    def _headroom(probe: Optional[Dict[str, Any]]) -> Optional[int]:
        if not probe:
            return None
        maximum = _as_int(probe.get("max_connections"))
        active = _as_int(probe.get("active"))
        if maximum is None or active is None:
            return None
        return maximum - active

    direct_latency = direct.get("latency_ms")
    pooled_latency = pooled.get("latency_ms") if pooled else None
    delta = None
    if isinstance(direct_latency, (int, float)) and isinstance(pooled_latency, (int, float)):
        delta = round(float(pooled_latency) - float(direct_latency), 3)
    partial = pooled is None or pooled.get("status") == "not_available"
    reason = None
    if pooled is None:
        reason = (
            "No pooled connection was supplied. "
            "The direct server was measured; a pooler endpoint was not guessed."
        )
    elif pooled.get("status") == "not_available":
        reason = pooled.get("reason")
    return {
        "ok": True,
        "status": "partial" if partial else "ok",
        "direct": {**direct, "headroom": _headroom(direct)},
        "pooled": None
        if pooled is None
        else {**pooled, "headroom": _headroom(pooled)},
        "latency_delta_ms": delta,
        "reason": reason,
        "permission": RUN_PERMISSION,
    }


def _unavailable(engine: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_available",
        "engine": engine,
        "reason": reason,
        "latency_ms": None,
        "max_connections": None,
        "active": None,
        "pool_mode": None,
        "permission": RUN_PERMISSION,
    }


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _cursor(connection: Any):
    raw = getattr(connection, "connection", None)
    if raw is None and hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    return raw.cursor()


def _one(connection: Any, sql: str) -> Dict[str, Any]:
    cursor = _cursor(connection)
    try:
        cursor.execute(sql)
        description = cursor.description or []
        columns = [col[0] for col in description]
        row = cursor.fetchone()
        if row is None:
            return {}
        return dict(zip(columns, row))
    finally:
        cursor.close()


def _permission_denied(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "permission denied" in text or "42501" in text


def probe_postgres(connection: Any) -> Dict[str, Any]:
    """Measure one PostgreSQL connection. Pool mode stays null when unsupported."""
    engine = _engine_name(connection)
    if engine != "postgresql":
        return _unavailable(
            engine,
            "Pooler health reads PostgreSQL. "
            + (f"This connection is {engine}." if engine else "A connection type is required."),
        )
    started = time.perf_counter()
    try:
        _one(connection, _PING_SQL)
    except Exception as exc:
        if _permission_denied(exc):
            return _unavailable(engine, "Not available on this role: " + str(exc))
        return _unavailable(engine, str(exc))
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    try:
        head = _one(connection, _HEADROOM_SQL)
    except Exception as exc:
        if _permission_denied(exc):
            return _unavailable(engine, "Not available on this role: " + str(exc))
        head = {}
    pool_mode = None
    pool_mode_status = "not_available"
    try:
        mode_row = _one(connection, _POOL_MODE_SQL)
        if mode_row:
            pool_mode = str(next(iter(mode_row.values())))
            pool_mode_status = "ok"
    except Exception:
        pool_mode = None
        pool_mode_status = "not_available"
    return {
        "ok": True,
        "status": "ok",
        "engine": engine,
        "latency_ms": latency_ms,
        "max_connections": _as_int(head.get("max_connections")),
        "active": _as_int(head.get("active")),
        "pool_mode": pool_mode,
        "pool_mode_status": pool_mode_status,
        "permission": RUN_PERMISSION,
    }


class PoolerHealthPlugin(Plugin):
    """Premium plugin: direct vs pooled PostgreSQL health."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(
        self,
        connection: Any = None,
        pooled: Any = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        if connection is None:
            return _unavailable(None, "A direct database connection is required")
        direct = probe_postgres(connection)
        if direct.get("status") == "not_available" and not direct.get("ok", True):
            return direct
        if direct.get("ok") is False:
            return direct
        pooled_probe = probe_postgres(pooled) if pooled is not None else None
        report = assess(direct, pooled_probe)
        report["engine"] = "postgresql"
        return report

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = PoolerHealthPlugin
