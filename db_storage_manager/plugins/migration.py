"""
Database migration plugin.

Copies user tables from one live connection to another of the same engine
(SQLite, PostgreSQL, or MySQL). Existing tables are left in place. Replacing
rows requires the same typed confirmation as a backup restore: the target
database name (the file name, for SQLite). There is no DROP.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

from ..backups.manager import BackupManager
from ..db.base import ConnectionConfig, DatabaseConnection
from ..security.auth import get_auth_manager
from .base import Plugin, PluginMetadata, PluginType
from .live_tables import (
    SUPPORTED_ENGINES,
    close_db,
    column_names,
    config_secrets,
    count_rows,
    create_table_sql,
    database_identity,
    engine_name,
    list_tables,
    open_db,
    public_error,
    quote_ident,
    read_table,
    rollback,
    server_column_defs,
    sqlite_create_sql,
    write_table,
)
from .sdk import not_available

READ_PERMISSION = "query:execute"
WRITE_PERMISSION = "query:write"


class MigrationPlugin(Plugin):
    """Copy tables between two live databases. No destructive default."""

    def __init__(self):
        metadata = PluginMetadata(
            name="migration",
            version="1.0.0",
            author="VoxHash",
            description="Database schema migration tools",
            plugin_type=PluginType.MIGRATION,
            plugin_id="migration",
        )
        super().__init__(metadata)
        self.source_db: Optional[DatabaseConnection] = None
        self.target_db: Optional[DatabaseConnection] = None

    def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize migration plugin"""
        return True

    def execute(
        self,
        source_db: Any = None,
        target_db: Any = None,
        tables: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Copy tables from ``source_db`` to ``target_db``."""
        source = (
            source_db if source_db is not None else kwargs.get("connection")
        )
        target = target_db if target_db is not None else kwargs.get("other")
        if tables is None:
            tables = kwargs.get("tables")
        replace = bool(kwargs.get("replace"))
        confirm = str(
            kwargs.get("confirm") or kwargs.get("confirmation") or ""
        )
        return _run_async(
            _migrate(
                source,
                target,
                tables=_table_names(tables),
                replace=replace,
                confirm=confirm,
            )
        )

    def cleanup(self) -> None:
        """Cleanup migration plugin"""
        self.source_db = None
        self.target_db = None


def _table_names(tables: Any) -> Optional[List[str]]:
    if tables is None:
        return None
    if isinstance(tables, str):
        tables = [part.strip() for part in tables.split(",")]
    names = [str(name).strip() for name in tables if str(name).strip()]
    return names


def _missing_permission() -> Optional[str]:
    auth = get_auth_manager()
    if not auth.has_permission(READ_PERMISSION):
        return READ_PERMISSION
    if not auth.has_permission(WRITE_PERMISSION):
        return WRITE_PERMISSION
    return None


async def _migrate(
    source: Any,
    target: Any,
    *,
    tables: Optional[List[str]],
    replace: bool,
    confirm: str,
) -> Dict[str, Any]:
    source_engine = engine_name(source)
    target_engine = engine_name(target)
    if source is None or target is None:
        return not_available(
            "A source connection and a target connection are required",
            engine=source_engine or target_engine,
            tables_migrated=[],
        )
    if source is target or _same_database(source, target):
        return not_available(
            "Source and target are the same database",
            engine=source_engine,
            tables_migrated=[],
        )
    denied = _missing_permission()
    if denied:
        return not_available(
            f"{denied} is required to copy tables",
            engine=source_engine,
            permission=denied,
            tables_migrated=[],
        )
    if source_engine not in SUPPORTED_ENGINES:
        return not_available(
            "Migration copies SQLite, PostgreSQL and MySQL. "
            + (
                f"This source is {source_engine}."
                if source_engine
                else "A source engine is required."
            ),
            engine=source_engine,
            tables_migrated=[],
        )
    if target_engine != source_engine:
        return not_available(
            "Source and target must be the same engine. "
            f"Source is {source_engine}; target is {target_engine or 'unknown'}.",
            engine=source_engine,
            tables_migrated=[],
        )

    secrets = config_secrets(source) + config_secrets(target)
    source_db: Optional[DatabaseConnection] = None
    target_db: Optional[DatabaseConnection] = None
    source_opened = False
    target_opened = False
    try:
        source_db, source_opened = await open_db(source)
        target_db, target_opened = await open_db(target)
        report = await _copy(
            source_db,
            target_db,
            source_engine,
            tables=tables,
            replace=replace,
            confirm=confirm,
        )
    except Exception as exc:
        report = not_available(
            public_error(exc, secrets),
            engine=source_engine,
            tables_migrated=[],
        )
    finally:
        if source_db is not None:
            await rollback(source_db)
            await close_db(source_db, source_opened)
        if target_db is not None:
            await rollback(target_db)
            await close_db(target_db, target_opened)
    _audit(report, source, target)
    return report


async def _copy(
    source_db: DatabaseConnection,
    target_db: DatabaseConnection,
    engine: str,
    *,
    tables: Optional[List[str]],
    replace: bool,
    confirm: str,
) -> Dict[str, Any]:
    source_tables = await list_tables(source_db, engine)
    await rollback(source_db)
    wanted = tables if tables is not None else list(source_tables)
    known = {name.casefold(): name for name in source_tables}
    phrase = _confirmation_phrase(target_db)
    confirmed = bool(phrase) and confirm.strip() == phrase
    actions: List[Dict[str, Any]] = []
    for requested in wanted:
        actual = known.get(str(requested).casefold())
        if actual is None:
            actions.append(
                {
                    "name": str(requested),
                    "action": "not_available",
                    "reason": "table is not on the source",
                }
            )
            continue
        actions.append(
            await _copy_one(
                source_db,
                target_db,
                engine,
                actual,
                confirmed=confirmed,
                replace=replace,
            )
        )
    return _summary(engine, actions, confirmed=confirmed, replace=replace)


async def _copy_one(
    source_db: DatabaseConnection,
    target_db: DatabaseConnection,
    engine: str,
    table: str,
    *,
    confirmed: bool,
    replace: bool,
) -> Dict[str, Any]:
    try:
        quote_ident(table, engine)
        columns, rows = await read_table(source_db, engine, table)
        await rollback(source_db)
        if not columns:
            return {
                "name": table,
                "action": "not_available",
                "reason": "table has no columns",
            }
        target_tables = await list_tables(target_db, engine)
        await rollback(target_db)
        exists = any(
            name.casefold() == table.casefold() for name in target_tables
        )
        create_sql = None
        delete_first = False
        if exists:
            target_columns = await column_names(target_db, engine, table)
            await rollback(target_db)
            if [name.casefold() for name in target_columns] != [
                name.casefold() for name in columns
            ]:
                return {
                    "name": table,
                    "action": "not_available",
                    "reason": "target columns differ; table was not changed",
                }
            present = await count_rows(target_db, engine, table)
            await rollback(target_db)
            if present:
                if not replace:
                    return {
                        "name": table,
                        "action": "skipped",
                        "reason": "table already exists and was not replaced",
                    }
                if not confirmed:
                    return {
                        "name": table,
                        "action": "not_available",
                        "reason": (
                            "confirmation does not match the target "
                            "database name; rows were not replaced"
                        ),
                    }
                delete_first = True
        else:
            create_sql = await _create_sql(source_db, engine, table)
            await rollback(source_db)
            if not create_sql:
                return {
                    "name": table,
                    "action": "not_available",
                    "reason": "table definition cannot be copied without guessing",
                }
        await write_table(
            target_db,
            engine,
            table,
            columns,
            rows,
            create_sql=create_sql,
            delete_first=delete_first,
        )
        return {"name": table, "action": "copied", "rows": len(rows)}
    except Exception as exc:
        await rollback(source_db)
        await rollback(target_db)
        return {
            "name": table,
            "action": "failed",
            "reason": public_error(
                exc, config_secrets(source_db) + config_secrets(target_db)
            ),
        }


async def _create_sql(
    source_db: DatabaseConnection, engine: str, table: str
) -> Optional[str]:
    if engine == "sqlite":
        return await sqlite_create_sql(source_db, table)
    defs = await server_column_defs(source_db, engine, table)
    return create_table_sql(engine, table, defs)


def _confirmation_phrase(target_db: DatabaseConnection) -> str:
    config = getattr(target_db, "config", None)
    if not isinstance(config, ConnectionConfig):
        return ""
    return BackupManager.restore_confirmation_phrase(config)


def _same_database(source: Any, target: Any) -> bool:
    left = database_identity(source)
    right = database_identity(target)
    if not left or left.endswith("|||") or left.endswith("||"):
        return False
    # An identity of only the engine (no host, port, database or URL) is not
    # enough to decide the two connections are the same.
    parts = [part for part in left.split("|") if part]
    if len(parts) <= 1:
        return False
    return left == right


def _summary(
    engine: str,
    actions: List[Dict[str, Any]],
    *,
    confirmed: bool,
    replace: bool,
) -> Dict[str, Any]:
    copied = [row["name"] for row in actions if row["action"] == "copied"]
    refused = [row for row in actions if row["action"] == "not_available"]
    failed = [row for row in actions if row["action"] == "failed"]
    if copied and not refused and not failed:
        status = "success"
        ok = True
        reason = ""
    elif copied:
        status = "partial"
        ok = True
        reason = ""
    elif refused and not failed:
        status = "not_available"
        ok = False
        reason = str(refused[0].get("reason") or "")
    elif failed:
        status = "not_available"
        ok = False
        reason = str(failed[0].get("reason") or "copy failed")
    else:
        status = "success"
        ok = True
        reason = ""
    report: Dict[str, Any] = {
        "ok": ok,
        "status": status,
        "engine": engine,
        "tables": actions,
        "tables_migrated": copied,
        "replace": replace,
        "confirmed": confirmed,
        "permission": WRITE_PERMISSION,
    }
    if reason:
        report["reason"] = reason
    return report


def _audit(report: Dict[str, Any], source: Any, target: Any) -> None:
    try:
        from ..audit import write_audit

        write_audit(
            "plugin.migration",
            str(report.get("status") or "not_available"),
            source_id=_object_id(source),
            target_id=_object_id(target),
            tables_migrated=list(report.get("tables_migrated") or []),
            table_count=len(report.get("tables") or []),
        )
    except Exception:
        return


def _object_id(connection: Any) -> str:
    config = getattr(connection, "config", None)
    if config is not None and getattr(config, "id", None):
        return str(config.id)
    if isinstance(connection, dict) and connection.get("id"):
        return str(connection["id"])
    return ""


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


PLUGIN_CLASS = MigrationPlugin
