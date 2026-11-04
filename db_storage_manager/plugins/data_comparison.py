"""
Data comparison plugin.

Reads one table from two live connections and reports row and column
differences. It does not write. Secret-named columns and DSMENC1 values are
redacted in the report. The audit record stores counts only.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from ..security.auth import get_auth_manager
from .base import Plugin, PluginMetadata, PluginType
from .live_tables import (
    SUPPORTED_ENGINES,
    Row,
    close_db,
    config_secrets,
    database_identity,
    engine_name,
    list_tables,
    open_db,
    public_error,
    quote_ident,
    read_table,
    redact_cell,
    rollback,
)
from .sdk import not_available

READ_PERMISSION = "query:execute"
_DIFF_LIMIT = 20


class DataComparisonPlugin(Plugin):
    """Compare rows in one table on two live databases."""

    def __init__(self):
        metadata = PluginMetadata(
            name="data_comparison",
            version="1.0.0",
            author="VoxHash",
            description="Compare data between databases",
            plugin_type=PluginType.DATA_COMPARISON,
            plugin_id="data_comparison",
        )
        super().__init__(metadata)

    def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize comparison plugin"""
        return True

    def execute(
        self,
        db1: Any = None,
        db2: Any = None,
        table: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Compare ``table`` on ``db1`` and ``db2``."""
        left = db1 if db1 is not None else kwargs.get("connection")
        right = db2 if db2 is not None else kwargs.get("other")
        name = table or str(kwargs.get("table") or "")
        return _run_async(_compare(left, right, name.strip()))

    def cleanup(self) -> None:
        """Cleanup comparison plugin"""
        pass


async def _compare(left: Any, right: Any, table: str) -> Dict[str, Any]:
    left_engine = engine_name(left)
    right_engine = engine_name(right)
    if left is None or right is None:
        return not_available(
            "Two database connections are required",
            engine=left_engine,
            matches=0,
            mismatches=0,
            differences=[],
        )
    if not table:
        return not_available(
            "A table name is required",
            engine=left_engine,
            matches=0,
            mismatches=0,
            differences=[],
        )
    auth = get_auth_manager()
    if not auth.has_permission(READ_PERMISSION):
        return not_available(
            f"{READ_PERMISSION} is required to compare tables",
            engine=left_engine,
            permission=READ_PERMISSION,
            matches=0,
            mismatches=0,
            differences=[],
        )
    for engine, side in ((left_engine, "source"), (right_engine, "target")):
        if engine not in SUPPORTED_ENGINES:
            return not_available(
                "Data comparison reads SQLite, PostgreSQL and MySQL. "
                + (
                    f"The {side} connection is {engine}."
                    if engine
                    else f"The {side} connection needs an engine."
                ),
                engine=engine,
                matches=0,
                mismatches=0,
                differences=[],
            )
    try:
        quote_ident(table, left_engine or "sqlite")
        quote_ident(table, right_engine or "sqlite")
    except ValueError:
        return not_available(
            "The table name is not a valid identifier",
            engine=left_engine,
            matches=0,
            mismatches=0,
            differences=[],
        )

    secrets = config_secrets(left) + config_secrets(right)
    left_db = None
    right_db = None
    left_opened = False
    right_opened = False
    try:
        left_db, left_opened = await open_db(left)
        right_db, right_opened = await open_db(right)
        report = await _compare_open(
            left_db,
            right_db,
            left_engine or "",
            right_engine or "",
            table,
        )
    except Exception as exc:
        report = not_available(
            public_error(exc, secrets),
            engine=left_engine,
            matches=0,
            mismatches=0,
            differences=[],
        )
    finally:
        if left_db is not None:
            await rollback(left_db)
            await close_db(left_db, left_opened)
        if right_db is not None:
            await rollback(right_db)
            await close_db(right_db, right_opened)
    _audit(report, left, right, table)
    return report


async def _compare_open(
    left_db: Any,
    right_db: Any,
    left_engine: str,
    right_engine: str,
    table: str,
) -> Dict[str, Any]:
    left_tables = await list_tables(left_db, left_engine)
    await rollback(left_db)
    right_tables = await list_tables(right_db, right_engine)
    await rollback(right_db)
    left_name = _match(left_tables, table)
    right_name = _match(right_tables, table)
    if left_name is None or right_name is None:
        missing = "source" if left_name is None else "target"
        return not_available(
            f"Table {table} is not on the {missing}",
            engine=left_engine,
            matches=0,
            mismatches=0,
            differences=[],
        )
    left_columns, left_rows = await read_table(left_db, left_engine, left_name)
    await rollback(left_db)
    right_columns, right_rows = await read_table(
        right_db, right_engine, right_name
    )
    await rollback(right_db)
    report = compare_loaded(left_columns, left_rows, right_columns, right_rows)
    report["engine"] = left_engine
    report["other_engine"] = right_engine
    report["table"] = table
    report["permission"] = READ_PERMISSION
    same = database_identity(left_db) == database_identity(right_db)
    report["same_database"] = bool(same)
    return report


def compare_loaded(
    left_columns: Sequence[str],
    left_rows: Sequence[Row],
    right_columns: Sequence[str],
    right_rows: Sequence[Row],
) -> Dict[str, Any]:
    """Compare already-loaded rows. Shared column names are compared."""
    left_names = [str(column) for column in left_columns]
    right_names = [str(column) for column in right_columns]
    right_fold = {name.casefold() for name in right_names}
    left_fold = {name.casefold() for name in left_names}
    shared = [name for name in left_names if name.casefold() in right_fold]
    only_left = [
        name for name in left_names if name.casefold() not in right_fold
    ]
    only_right = [
        name for name in right_names if name.casefold() not in left_fold
    ]
    if not shared:
        return not_available(
            "The tables have no column names in common",
            matches=0,
            mismatches=0,
            differences=[],
            columns={
                "shared": [],
                "only_source": only_left,
                "only_target": only_right,
            },
        )
    left_projected = _project(left_names, left_rows, shared)
    right_projected = _project(right_names, right_rows, shared)
    left_counts: Counter = Counter(left_projected)
    right_counts: Counter = Counter(right_projected)
    matches = sum((left_counts & right_counts).values())
    only_source = left_counts - right_counts
    only_target = right_counts - left_counts
    mismatches = sum(only_source.values()) + sum(only_target.values())
    differences: List[Dict[str, Any]] = []
    truncated = False
    for side, counts in (("source", only_source), ("target", only_target)):
        for row, count in counts.items():
            for _ in range(count):
                if len(differences) >= _DIFF_LIMIT:
                    truncated = True
                    break
                differences.append(
                    {
                        "side": side,
                        "values": {
                            column: redact_cell(column, value)
                            for column, value in zip(shared, row)
                        },
                    }
                )
            if truncated:
                break
        if truncated:
            break
    changed = bool(only_left or only_right or mismatches)
    return {
        "ok": True,
        "status": "diff" if changed else "match",
        "matches": matches,
        "mismatches": mismatches,
        "differences": differences,
        "differences_truncated": truncated,
        "columns": {
            "shared": shared,
            "only_source": only_left,
            "only_target": only_right,
        },
    }


def _project(
    columns: Sequence[str], rows: Sequence[Row], shared: Sequence[str]
) -> List[Row]:
    index = {str(column).casefold(): pos for pos, column in enumerate(columns)}
    projected: List[Row] = []
    for row in rows:
        projected.append(
            tuple(
                (
                    row[index[name.casefold()]]
                    if index[name.casefold()] < len(row)
                    else None
                )
                for name in shared
            )
        )
    return projected


def _match(names: Sequence[str], table: str) -> Optional[str]:
    for name in names:
        if name.casefold() == table.casefold():
            return name
    return None


def _audit(report: Dict[str, Any], left: Any, right: Any, table: str) -> None:
    try:
        from ..audit import write_audit

        write_audit(
            "plugin.data_comparison",
            str(report.get("status") or "not_available"),
            source_id=_object_id(left),
            target_id=_object_id(right),
            table=table,
            matches=int(report.get("matches") or 0),
            mismatches=int(report.get("mismatches") or 0),
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


PLUGIN_CLASS = DataComparisonPlugin
