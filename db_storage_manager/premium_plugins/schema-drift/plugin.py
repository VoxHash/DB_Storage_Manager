"""Schema drift — second first-party premium plugin.

Snapshots tables and columns from a live connection and diffs that snapshot
against a saved baseline or a second connection. Supported engines:

* SQLite — ``sqlite_master`` and ``PRAGMA table_info``
* PostgreSQL — ``information_schema.columns`` in ``public``
* MySQL / MariaDB — ``information_schema.columns`` for the connection database

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
A missing privilege is reported as not available; the plugin does not guess
that a table is absent. No credentials are bundled.

``plugin.json`` ``license.product_id`` is the monthly product
(``plugins.pricing.PREMIUM_PRODUCT_IDS["schema-drift"]["monthly"]``).
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "schema-drift"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"

_PG_SQL = """
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

_MYSQL_SQL = """
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = DATABASE()
ORDER BY table_name, ordinal_position
"""


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Schema drift",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Snapshot the schema and diff it against a baseline "
            "or another connection"
        ),
        plugin_type=PluginType.DATA_COMPARISON,
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
    if name == "mariadb":
        return "mysql"
    return name


def _quote_sqlite(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _column(name: str, type_name: str, nullable: bool) -> Dict[str, Any]:
    return {
        "name": str(name),
        "type": str(type_name or "").strip().lower(),
        "nullable": bool(nullable),
    }


def snapshot_from_rows(rows: List[Dict[str, Any]], *, engine: str) -> Dict[str, Any]:
    """Build a snapshot from information_schema-shaped rows."""
    tables: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        table = str(row["table_name"])
        nullable = str(row.get("is_nullable", "YES")).upper() != "NO"
        tables.setdefault(table, {"columns": []})
        tables[table]["columns"].append(
            _column(row["column_name"], row.get("data_type") or "", nullable)
        )
    return {"engine": engine, "tables": tables}


def snapshot_sqlite(raw: sqlite3.Connection) -> Dict[str, Any]:
    """Read tables and columns from an open SQLite connection."""
    cursor = raw.cursor()
    names = [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    tables: Dict[str, Dict[str, Any]] = {}
    for name in names:
        columns = []
        for info in cursor.execute(f"PRAGMA table_info({_quote_sqlite(name)})"):
            # cid, name, type, notnull, dflt_value, pk
            columns.append(_column(info[1], info[2], not bool(info[3])))
        tables[name] = {"columns": columns}
    return {"engine": "sqlite", "tables": tables}


def diff_snapshots(baseline: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Tables and columns added, removed, or changed between two snapshots."""
    before = baseline.get("tables") or {}
    after = current.get("tables") or {}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    columns_added: List[Dict[str, Any]] = []
    columns_removed: List[Dict[str, Any]] = []
    columns_changed: List[Dict[str, Any]] = []
    for table in sorted(set(before) & set(after)):
        bcols = {c["name"]: c for c in before[table].get("columns") or []}
        acols = {c["name"]: c for c in after[table].get("columns") or []}
        for name in sorted(set(acols) - set(bcols)):
            columns_added.append({"table": table, "column": name, **acols[name]})
        for name in sorted(set(bcols) - set(acols)):
            columns_removed.append({"table": table, "column": name, **bcols[name]})
        for name in sorted(set(bcols) & set(acols)):
            if bcols[name]["type"] != acols[name]["type"] or (
                bcols[name]["nullable"] != acols[name]["nullable"]
            ):
                columns_changed.append(
                    {
                        "table": table,
                        "column": name,
                        "before": bcols[name],
                        "after": acols[name],
                    }
                )
    changed = bool(added or removed or columns_added or columns_removed or columns_changed)
    return {
        "tables_added": added,
        "tables_removed": removed,
        "columns_added": columns_added,
        "columns_removed": columns_removed,
        "columns_changed": columns_changed,
        "changed": changed,
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


def _sqlite_path(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    if config is not None:
        path = config.database or config.connection_string
        if path:
            return str(path)
    if isinstance(connection, (str, Path)):
        return str(connection)
    return None


def _open_sqlite(connection: Any) -> sqlite3.Connection:
    """Read through the stdlib driver.

    The app's ``SQLiteConnection`` holds an aiosqlite connection. A second
    read-only sqlite3 connection to the same file is the catalog source.
    """
    raw = getattr(connection, "connection", None)
    if isinstance(raw, sqlite3.Connection):
        return raw
    path = _sqlite_path(connection)
    if path:
        return sqlite3.connect(path)
    raise RuntimeError("SQLite connection is not open")


def _query_server(connection: Any, sql: str) -> List[Dict[str, Any]]:
    raw = getattr(connection, "connection", None)
    if raw is None and hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        description = cursor.description or []
        columns = [col[0] for col in description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def snapshot_connection(connection: Any) -> Dict[str, Any]:
    """Snapshot the live schema. Raises ``RuntimeError`` when it cannot be read."""
    engine = _engine_name(connection)
    if engine == "sqlite":
        raw = getattr(connection, "connection", None)
        owned = None
        if not isinstance(raw, sqlite3.Connection):
            owned = _open_sqlite(connection)
            raw = owned
        try:
            return snapshot_sqlite(raw)
        finally:
            if owned is not None:
                owned.close()
    if engine == "postgresql":
        rows = _query_server(connection, _PG_SQL)
        return snapshot_from_rows(rows, engine=engine)
    if engine == "mysql":
        rows = _query_server(connection, _MYSQL_SQL)
        return snapshot_from_rows(rows, engine=engine)
    raise RuntimeError(
        "Schema drift reads SQLite, PostgreSQL and MySQL catalogs. "
        + (f"This connection is {engine}." if engine else "A connection type is required.")
    )


class SchemaDriftPlugin(Plugin):
    """Premium plugin: schema snapshot and diff."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(
        self,
        connection: Any = None,
        baseline: Any = None,
        other: Any = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        engine = _engine_name(connection)
        if connection is None:
            return _unavailable(None, "A database connection is required")
        try:
            current = snapshot_connection(connection)
        except Exception as exc:
            text = str(exc).lower()
            if "permission denied" in text or "access denied" in text:
                return _unavailable(
                    engine,
                    "Not available on this role: " + str(exc),
                )
            return _unavailable(engine, str(exc))

        compare_to = None
        if other is not None:
            try:
                compare_to = snapshot_connection(other)
            except Exception as exc:
                return _unavailable(_engine_name(other) or engine, str(exc))
        elif isinstance(baseline, dict) and "tables" in baseline:
            compare_to = baseline

        if compare_to is None:
            return {
                "ok": True,
                "status": "snapshot",
                "engine": current["engine"],
                "snapshot": current,
                "permission": RUN_PERMISSION,
            }
        report = diff_snapshots(compare_to, current)
        return {
            "ok": True,
            "status": "diff",
            "engine": current["engine"],
            "snapshot": current,
            "diff": report,
            "permission": RUN_PERMISSION,
        }

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = SchemaDriftPlugin
