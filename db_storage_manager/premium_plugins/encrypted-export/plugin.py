"""Encrypted export — one table, DSMENC1 envelope, optional redaction.

CSV and SQL are written with the stdlib. Parquet is written only when pandas
can import a parquet engine; otherwise that format is ``not_available`` and
no file is left behind. Column values named in ``redact`` are replaced before
the plaintext file is encrypted. The plaintext file is removed in a finally
block. The passphrase is not stored and not returned.

Install requires ``plugins:manage``. Running requires ``backups:create``
because the result is a backup-like file of table contents.
``license.product_id`` is ``PREMIUM_PRODUCT_IDS["encrypted-export"]["monthly"]``.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "encrypted-export"
RUN_PERMISSION = "backups:create"
INSTALL_PERMISSION = "plugins:manage"
REDACTED = "REDACTED"
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORMATS = frozenset({"csv", "sql", "parquet"})


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Encrypted export",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Export one table to CSV, SQL or Parquet inside a DSMENC1 file, "
            "with optional column redaction"
        ),
        plugin_type=PluginType.CUSTOM,
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


def _quote_ident(name: str, engine: str) -> str:
    if engine == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _redact_row(
    columns: Sequence[str], row: Sequence[Any], redact: Iterable[str]
) -> List[Any]:
    wanted = {name.casefold() for name in redact}
    out = list(row)
    for index, column in enumerate(columns):
        if column.casefold() in wanted and out[index] is not None:
            out[index] = REDACTED
    return out


def _unavailable(engine: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_available",
        "engine": engine,
        "reason": reason,
        "permission": RUN_PERMISSION,
    }


def _fail(engine: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "fail",
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


def _open_reader(connection: Any, engine: str):
    """Return ``(cursor, close)`` for a read of one table."""
    if engine == "sqlite":
        raw = getattr(connection, "connection", None)
        if isinstance(raw, sqlite3.Connection):
            return raw.cursor(), (lambda: None)
        path = _sqlite_path(connection)
        if not path:
            raise RuntimeError("SQLite connection is not open")
        owned = sqlite3.connect(path)
        return owned.cursor(), owned.close
    raw = getattr(connection, "connection", None)
    if raw is None and hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    return raw.cursor(), (lambda: None)


def _table_exists_sqlite(cursor: sqlite3.Cursor, table: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _write_plaintext(
    path: Path,
    engine: str,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    fmt: str,
) -> int:
    count = 0
    quoted = _quote_ident(table, engine)
    if fmt == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(list(columns))
            for row in rows:
                writer.writerow(list(row))
                count += 1
        return count
    if fmt == "sql":
        col_sql = ", ".join(_quote_ident(column, engine) for column in columns)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                values = ", ".join(_sql_literal(value) for value in row)
                handle.write(f"INSERT INTO {quoted} ({col_sql}) VALUES ({values});\n")
                count += 1
        return count
    if fmt == "parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("Parquet export needs pandas") from exc
        frame = pd.DataFrame(list(rows), columns=list(columns))
        count = len(frame.index)
        try:
            frame.to_parquet(path, index=False)
        except Exception as exc:
            raise RuntimeError(
                "Parquet export is not available on this machine: " + str(exc)
            ) from exc
        return count
    raise ValueError("format must be csv, sql or parquet")


def _select_sql(engine: str, table: str) -> str:
    if engine == "postgresql":
        return f"SELECT * FROM {_quote_ident('public', engine)}.{_quote_ident(table, engine)}"
    return f"SELECT * FROM {_quote_ident(table, engine)}"


def export_table(
    connection: Any,
    table: str,
    dest: Path,
    passphrase: str,
    *,
    fmt: str = "csv",
    redact: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Read ``table``, redact, encrypt to ``dest``. Plaintext is deleted."""
    engine = _engine_name(connection)
    if engine not in {"sqlite", "postgresql", "mysql"}:
        return _unavailable(
            engine,
            "Encrypted export reads SQLite, PostgreSQL and MySQL. "
            + (f"This connection is {engine}." if engine else "A connection type is required."),
        )
    if not _TABLE_RE.fullmatch(table or ""):
        return _fail(
            engine,
            "Table name must be letters, digits and underscores, starting with a letter or underscore",
        )
    if fmt not in _FORMATS:
        return _fail(engine, "format must be csv, sql or parquet")
    if not passphrase:
        return _fail(engine, "A passphrase is required")

    redact_names = [str(name) for name in (redact or [])]
    cursor, close = _open_reader(connection, engine)
    plain = dest.with_name(dest.name + ".plain")
    try:
        if engine == "sqlite" and not _table_exists_sqlite(cursor, table):
            return _fail(engine, f"Table {table} was not found")
        cursor.execute(_select_sql(engine, table))
        description = cursor.description or []
        columns = [col[0] for col in description]
        if not columns:
            return _fail(engine, f"Table {table} has no columns")

        def _rows():
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                for row in batch:
                    yield _redact_row(columns, row, redact_names)

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            count = _write_plaintext(plain, engine, table, columns, _rows(), fmt)
        except RuntimeError as exc:
            if fmt == "parquet":
                return _unavailable(engine, str(exc))
            return _fail(engine, str(exc))
        from db_storage_manager.native import encrypt_file

        try:
            encrypt_file(plain, dest, passphrase)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        if os.name != "nt":
            os.chmod(dest, 0o600)
        redacted_present = [
            column for column in columns if column.casefold() in {n.casefold() for n in redact_names}
        ]
        return {
            "ok": True,
            "status": "exported",
            "engine": engine,
            "format": fmt,
            "table": table,
            "rows": count,
            "redacted_columns": redacted_present,
            "path": str(dest),
            "envelope": "DSMENC1",
            "permission": RUN_PERMISSION,
        }
    except Exception as exc:
        text = str(exc).lower()
        if "permission denied" in text or "access denied" in text or "42501" in text:
            return _unavailable(engine, "Not available on this role: " + str(exc))
        if "no such table" in text or "does not exist" in text or "doesn't exist" in text:
            return _fail(engine, f"Table {table} was not found")
        return _fail(engine, str(exc))
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        close()
        try:
            plain.unlink(missing_ok=True)
        except OSError:
            pass


class EncryptedExportPlugin(Plugin):
    """Premium plugin: one table, encrypted, with optional redaction."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(
        self,
        connection: Any = None,
        table: str = "",
        dest: Any = None,
        passphrase: str = "",
        format: str = "csv",
        redact: Optional[Sequence[str]] = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        engine = _engine_name(connection)
        if connection is None or dest is None:
            return _fail(engine, "A connection and a destination path are required")
        return export_table(
            connection,
            str(table),
            Path(dest),
            passphrase,
            fmt=str(format or "csv"),
            redact=redact,
        )

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = EncryptedExportPlugin
