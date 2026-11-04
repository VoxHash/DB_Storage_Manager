"""Opt-in health checks across several saved connections.

One process polls the connections the operator listed. Credentials stay in
SecureStore. The poll is a health check (``SELECT 1`` and the existing
collector), not an arbitrary SQL runner. It does not grant ``query:*`` or
``backups:*``. A connection that cannot be read is ``not_available``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from ..security.auth import PermissionDenied, get_auth_manager

PLUGIN_ID = "multi-connection-monitor"
SETTINGS_KEY = "multi_connection_monitor"
_last_poll: Optional[float] = None


def reset_state() -> None:
    global _last_poll
    _last_poll = None


def _load() -> Dict[str, Any]:
    from ..security.store import SecureStore

    raw = SecureStore().get_settings().get(SETTINGS_KEY)
    if not isinstance(raw, dict):
        raw = {}
    ids = raw.get("connection_ids")
    if not isinstance(ids, list):
        ids = []
    try:
        interval = int(raw.get("min_interval_seconds") or 60)
    except (TypeError, ValueError):
        interval = 60
    return {
        "connection_ids": [str(item) for item in ids if str(item).strip()],
        "min_interval_seconds": max(60, interval),
    }


def _save(connection_ids: List[str], interval: int) -> None:
    from ..security.store import SecureStore

    store = SecureStore()
    settings = store.get_settings()
    settings[SETTINGS_KEY] = {
        "connection_ids": list(connection_ids),
        "min_interval_seconds": max(60, int(interval)),
    }
    store.set_settings(settings)


def _connections_by_id() -> Dict[str, Dict[str, Any]]:
    from ..security.store import SecureStore

    found: Dict[str, Dict[str, Any]] = {}
    for row in SecureStore().get_connections():
        if isinstance(row, dict) and row.get("id"):
            found[str(row["id"])] = row
    return found


def _config_from(raw: Dict[str, Any]):
    from ..db.base import ConnectionConfig

    allowed = (
        "id",
        "name",
        "type",
        "host",
        "port",
        "database",
        "username",
        "password",
        "connection_string",
        "ssh_config",
        "extra",
    )
    kwargs = {key: raw[key] for key in allowed if key in raw and raw[key] is not None}
    kwargs.setdefault("id", str(raw.get("id")))
    kwargs.setdefault("name", str(raw.get("name") or raw.get("id")))
    kwargs.setdefault("type", str(raw.get("type") or "sqlite"))
    return ConnectionConfig(**kwargs)


async def _health(raw: Dict[str, Any]) -> Dict[str, Any]:
    from ..db.base import DatabaseConnectionFactory
    from .health import HealthChecker

    connection = await DatabaseConnectionFactory.acquire(_config_from(raw))
    try:
        report = await HealthChecker(connection).check_health()
    finally:
        await DatabaseConnectionFactory.release(connection)
    return {
        "status": report.get("status") or "not_available",
        "summary": str(report.get("summary") or ""),
    }


def _installed() -> bool:
    from pathlib import Path

    from ..plugins.marketplace import LocalPluginMarketplace

    market = LocalPluginMarketplace()
    for row in market.list_installed():
        if row.get("id") != PLUGIN_ID or row.get("source") == "builtin":
            continue
        if not market.is_enabled(PLUGIN_ID):
            return False
        path = row.get("path")
        return bool(path and Path(path).is_dir())
    return False


def watch(
    *,
    connection_ids: Optional[List[str]] = None,
    poll: Optional[Callable[[str], Dict[str, Any]]] = None,
    clock: Callable[[], float] = time.monotonic,
    require_installed: bool = False,
) -> Dict[str, Any]:
    """Poll opted-in connections.

    Passing ``connection_ids`` saves the list and needs ``settings:write``.
    Polling needs ``monitoring:read``. ``poll`` is a test hook that receives
    the connection id and must not be given the password.
    """
    global _last_poll
    if require_installed and not _installed():
        return {
            "status": "not_available",
            "reason": "multi-connection-monitor is not installed.",
            "connections": [],
        }
    cfg = _load()
    if connection_ids is not None:
        get_auth_manager().require("settings:write")
        cfg["connection_ids"] = [str(item).strip() for item in connection_ids if str(item).strip()]
        _save(cfg["connection_ids"], cfg["min_interval_seconds"])
    try:
        get_auth_manager().require("monitoring:read")
    except PermissionDenied:
        return {
            "status": "not_available",
            "reason": "Not available on this role.",
            "connections": [],
        }
    if not cfg["connection_ids"]:
        return {
            "status": "not_available",
            "reason": "No connection is opted in.",
            "connections": [],
        }
    now = clock()
    if _last_poll is not None and now - _last_poll < cfg["min_interval_seconds"]:
        return {
            "status": "not_available",
            "reason": "Rate limited.",
            "connections": [],
        }
    _last_poll = now
    known = _connections_by_id()
    results: List[Dict[str, Any]] = []
    for connection_id in cfg["connection_ids"]:
        raw = known.get(connection_id)
        if raw is None:
            results.append(
                {
                    "id": connection_id,
                    "status": "not_available",
                    "summary": "Unknown connection.",
                }
            )
            continue
        try:
            if poll is not None:
                health = poll(connection_id)
            else:
                health = asyncio.run(_health(raw))
        except Exception as exc:  # noqa: BLE001 - do not guess healthy or unhealthy
            results.append(
                {
                    "id": connection_id,
                    "status": "not_available",
                    "summary": type(exc).__name__,
                }
            )
            continue
        if not isinstance(health, dict):
            health = {}
        results.append(
            {
                "id": connection_id,
                "status": str(health.get("status") or "not_available"),
                "summary": str(health.get("summary") or ""),
            }
        )
    return {"status": "ok", "connections": results}


def watch_if_installed() -> Optional[Dict[str, Any]]:
    """Used at launch. Does nothing until the plugin is installed and enabled."""
    if not _installed():
        return None
    try:
        return watch(require_installed=True)
    except Exception:
        return None
