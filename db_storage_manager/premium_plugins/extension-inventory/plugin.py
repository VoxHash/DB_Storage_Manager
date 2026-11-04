"""Extension inventory — installed versus available PostgreSQL extensions.

Reads ``pg_available_extensions``. A missing privilege is ``not_available``.
SQLite and MySQL have no ``pg_available_extensions``, so they are
``not_available`` rather than an empty inventory.

``xml2`` is deprecated in the PostgreSQL manual
(https://www.postgresql.org/docs/current/xml2.html). ``intagg`` is obsolete
(https://www.postgresql.org/docs/current/intagg.html). ``tsearch2`` was
removed from the core distribution. An installed copy of any of those is a
finding. An installed version other than ``default_version`` is listed as
outdated; PostgreSQL recommends the current minor of an extension.

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
``license.product_id`` is ``PREMIUM_PRODUCT_IDS["extension-inventory"]["monthly"]``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "extension-inventory"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"

# Names the current PostgreSQL documentation calls deprecated, obsolete, or removed.
DEPRECATED_EXTENSIONS = frozenset({"xml2", "intagg", "tsearch2"})

_SQL = """
SELECT name, default_version, installed_version, comment
FROM pg_available_extensions
ORDER BY name
"""


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Extension inventory",
        version="1.0.0",
        author="VoxHash",
        description=(
            "List installed and available PostgreSQL extensions and flag "
            "deprecated or outdated ones"
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


def classify_extensions(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn ``pg_available_extensions`` rows into an inventory. No database I/O."""
    installed = []
    available = []
    deprecated = []
    outdated = []
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        default_version = row.get("default_version")
        installed_version = row.get("installed_version")
        entry = {
            "name": name,
            "default_version": default_version,
            "installed_version": installed_version,
        }
        available.append({"name": name, "default_version": default_version})
        if installed_version in (None, ""):
            continue
        installed.append(entry)
        if name in DEPRECATED_EXTENSIONS:
            deprecated.append(dict(entry))
        elif (
            default_version not in (None, "")
            and str(installed_version) != str(default_version)
        ):
            outdated.append(dict(entry))
    status = "fail" if deprecated else "ok"
    return {
        "ok": True,
        "status": status,
        "installed": installed,
        "available_count": len(available),
        "deprecated": deprecated,
        "outdated": outdated,
        "permission": RUN_PERMISSION,
    }


def _unavailable(engine: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_available",
        "engine": engine,
        "reason": reason,
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


def _query(connection: Any, sql: str) -> List[Dict[str, Any]]:
    raw = getattr(connection, "connection", None)
    if raw is None and hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        columns = [col[0] for col in (cursor.description or [])]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _permission_denied(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "permission denied" in text or "42501" in text or "not authorized" in text


class ExtensionInventoryPlugin(Plugin):
    """Premium plugin: PostgreSQL extension inventory."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, connection: Any = None, **kwargs: Any) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        rows = kwargs.get("rows")
        engine = _engine_name(connection)
        if rows is None:
            if connection is None:
                return _unavailable(None, "A database connection is required")
            if engine != "postgresql":
                return _unavailable(
                    engine,
                    "pg_available_extensions is a PostgreSQL catalog. "
                    + (
                        f"This connection is {engine}."
                        if engine
                        else "A connection type is required."
                    ),
                )
            try:
                rows = _query(connection, _SQL)
            except Exception as exc:
                if _permission_denied(exc):
                    return _unavailable(engine, "Not available on this role: " + str(exc))
                return _unavailable(engine, str(exc))
        report = classify_extensions(rows)
        report["engine"] = engine or "postgresql"
        return report

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = ExtensionInventoryPlugin
