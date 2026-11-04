"""Read and write user tables through a live database adapter.

SQLite, PostgreSQL and MySQL only. Reads are ``SELECT``. Writes are the
``CREATE TABLE`` / ``DELETE`` / ``INSERT`` statements this module builds.
Identifiers are quoted. Values are bound as parameters. Nothing here logs
row contents, passwords or ``DSMENC1`` payloads.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..db.base import ConnectionConfig, DatabaseConnection
from ..db.factory import DatabaseConnectionFactory
from ..db.session import ensure_tunnel_for_connection

SUPPORTED_ENGINES = ("sqlite", "postgresql", "mysql")
_SECRET_COLUMN = re.compile(
    r"password|passphrase|secret|token|credential|dsn",
    re.IGNORECASE,
)
_TYPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_ ]*(?:\([0-9]+(?:,[0-9]+)?\))?")
_FORBIDDEN_KEY = (
    "password",
    "passphrase",
    "secret",
    "token",
    "credential",
    "connection_string",
    "dsn",
)

Row = Tuple[Any, ...]


def engine_name(connection: Any) -> Optional[str]:
    """Normalise a connection, config or profile to an engine name."""
    raw = None
    if isinstance(connection, ConnectionConfig):
        raw = connection.type
    elif isinstance(connection, dict):
        raw = connection.get("type")
    else:
        config = getattr(connection, "config", None)
        raw = getattr(config, "type", None) if config is not None else None
    if raw is None:
        return None
    name = str(raw).strip().lower()
    if name in {"postgres", "supabase"}:
        return "postgresql"
    if name == "mariadb":
        return "mysql"
    return name


def database_identity(connection: Any) -> str:
    """Host, port and database, so a copy onto itself can be refused."""
    config = _config_of(connection)
    if config is None and isinstance(connection, dict):
        engine = engine_name(connection) or ""
        return "|".join(
            [
                engine,
                str(connection.get("host") or ""),
                str(connection.get("port") or ""),
                str(connection.get("database") or ""),
                str(connection.get("connection_string") or ""),
            ]
        )
    if config is None:
        return ""
    return "|".join(
        [
            engine_name(config) or "",
            str(config.host or ""),
            str(config.port or ""),
            str(config.database or ""),
            str(config.connection_string or ""),
        ]
    )


def config_secrets(connection: Any) -> List[str]:
    """Secret strings that must not be copied into a result or a log line."""
    found: List[str] = []
    config = _config_of(connection)
    if config is not None:
        _collect_secret(found, getattr(config, "password", None))
        _collect_secret(found, getattr(config, "connection_string", None))
        ssh = getattr(config, "ssh_config", None) or {}
        if isinstance(ssh, dict):
            for key, value in ssh.items():
                if (
                    "password" in str(key).lower()
                    or "secret" in str(key).lower()
                ):
                    _collect_secret(found, value)
    if isinstance(connection, dict):
        _collect_secret(found, connection.get("password"))
        _collect_secret(found, connection.get("connection_string"))
        ssh = connection.get("ssh_config") or {}
        if isinstance(ssh, dict):
            for key, value in ssh.items():
                if "password" in str(key).lower():
                    _collect_secret(found, value)
    return found


def public_error(exc: BaseException, secrets: Sequence[str] = ()) -> str:
    """Short error text with secrets and DSMENC1 payloads removed."""
    text = str(exc) or type(exc).__name__
    for secret in secrets:
        if secret and len(secret) >= 4 and secret in text:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"DSMENC1\S*", "[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 300:
        text = text[:300] + "…"
    return text


def scrub(value: Any) -> Any:
    """Drop secret keys and DSMENC1 text from a value shown to the operator."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(bad in lowered for bad in _FORBIDDEN_KEY):
                continue
            cleaned[str(key)] = scrub(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    if isinstance(value, str) and "DSMENC1" in value:
        return "[redacted]"
    return value


def redact_cell(column: str, value: Any) -> Any:
    """Value safe to put in a comparison report."""
    if _SECRET_COLUMN.search(str(column)):
        return "[redacted]"
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        if b"DSMENC1" in bytes(value):
            return "[redacted]"
        return {"bytes": len(value)}
    if isinstance(value, str):
        if "DSMENC1" in value:
            return "[redacted]"
        if len(value) > 200:
            return value[:200] + "…"
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if "DSMENC1" in text:
        return "[redacted]"
    if len(text) > 200:
        return text[:200] + "…"
    return text


def quote_ident(name: str, engine: str) -> str:
    """Quote a table or column name. Rejects empty names and NUL."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("invalid identifier")
    if engine == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    """SQL string literal. Used only for catalog filters, never for row data."""
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("invalid text")
    return "'" + value.replace("'", "''") + "'"


def format_data_type(row: Dict[str, Any]) -> Optional[str]:
    """information_schema type, or None when copying it would be a guess."""
    data_type = str(row.get("data_type") or "").strip().lower()
    if not data_type or data_type == "user-defined":
        return None
    try:
        length = row.get("character_maximum_length")
        if data_type in {"character varying", "varchar"} and length not in (
            None,
            "",
        ):
            return f"varchar({int(length)})"
        if data_type in {"character", "char"} and length not in (None, ""):
            return f"char({int(length)})"
        if data_type == "numeric" and row.get("numeric_precision") not in (
            None,
            "",
        ):
            precision = int(row["numeric_precision"])
            scale = row.get("numeric_scale")
            if scale not in (None, ""):
                return f"numeric({precision},{int(scale)})"
            return f"numeric({precision})"
    except (TypeError, ValueError):
        return None
    if _TYPE_RE.fullmatch(data_type):
        return data_type
    return None


def create_table_sql(
    engine: str, table: str, columns: Sequence[Dict[str, Any]]
) -> str:
    """CREATE TABLE from column name, type and nullability. No defaults."""
    if engine not in {"postgresql", "mysql"}:
        raise ValueError("engine")
    if not columns:
        raise ValueError("columns")
    parts: List[str] = []
    for column in columns:
        typ = str(column.get("type") or "")
        if not _TYPE_RE.fullmatch(typ):
            raise ValueError("unsafe type")
        piece = quote_ident(str(column["name"]), engine) + " " + typ
        if not column.get("nullable", True):
            piece += " NOT NULL"
        parts.append(piece)
    return (
        f"CREATE TABLE {quote_ident(table, engine)} (" + ", ".join(parts) + ")"
    )


def acceptable_create(sql: str) -> bool:
    """True when ``sql`` is one CREATE TABLE statement from sqlite_master."""
    compact = " ".join(str(sql or "").strip().split())
    body = compact[:-1] if compact.endswith(";") else compact
    if not body or ";" in body:
        return False
    return body.upper().startswith("CREATE TABLE ")


def connection_from_profile(profile: Dict[str, Any]) -> DatabaseConnection:
    """Unconnected adapter for a saved connection profile."""
    kwargs = ensure_tunnel_for_connection(profile)
    return DatabaseConnectionFactory.create_connection(
        ConnectionConfig(**kwargs)
    )


async def open_db(value: Any) -> Tuple[DatabaseConnection, bool]:
    """Return a connected adapter and whether this call opened it."""
    if isinstance(value, DatabaseConnection):
        if not value.connected or value.connection is None:
            await value.connect()
            return value, True
        return value, False
    if isinstance(value, (ConnectionConfig, dict)):
        if isinstance(value, ConnectionConfig):
            db = DatabaseConnectionFactory.create_connection(value)
        else:
            db = connection_from_profile(value)
        try:
            await db.connect()
        except Exception:
            await close_db(db, True)
            raise
        return db, True
    raise TypeError("A database connection is required")


async def close_db(db: DatabaseConnection, opened: bool) -> None:
    """Disconnect a connection this module opened."""
    if not opened:
        return
    try:
        await db.disconnect()
    except Exception:
        db.connection = None
        db.connected = False


async def rollback(db: DatabaseConnection) -> None:
    """End a read transaction so the file or row lock is released."""
    raw = getattr(db, "connection", None)
    if raw is None:
        return
    try:
        result = raw.rollback()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        return


async def fetch_select(
    db: DatabaseConnection, engine: str, sql: str
) -> Tuple[List[str], List[Row]]:
    """Run one SELECT on the live adapter connection."""
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("only SELECT is used to read tables")
    raw = getattr(db, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    if engine == "sqlite":
        cursor = await raw.execute(sql)
        description = cursor.description or []
        columns = [str(col[0]) for col in description]
        rows: List[Row] = []
        while True:
            batch = await cursor.fetchmany(500)
            if not batch:
                break
            rows.extend(tuple(row) for row in batch)
        return columns, rows
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        description = cursor.description or []
        columns = [str(col[0]) for col in description]
        rows = []
        while True:
            batch = cursor.fetchmany(500)
            if not batch:
                break
            rows.extend(tuple(row) for row in batch)
        return columns, rows
    finally:
        cursor.close()


async def list_tables(db: DatabaseConnection, engine: str) -> List[str]:
    """User tables. PostgreSQL is limited to ``public``, matching schema drift."""
    if engine == "sqlite":
        sql = (
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    elif engine == "postgresql":
        sql = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    elif engine == "mysql":
        sql = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    else:
        raise ValueError("unsupported engine")
    _columns, rows = await fetch_select(db, engine, sql)
    names = []
    for row in rows:
        if row and row[0] is not None:
            names.append(str(row[0]))
    return names


async def column_names(
    db: DatabaseConnection, engine: str, table: str
) -> List[str]:
    """Column names in table order."""
    if engine == "sqlite":
        sql = (
            "SELECT name FROM pragma_table_info("
            + sql_string(table)
            + ") ORDER BY cid"
        )
    elif engine == "postgresql":
        sql = (
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = "
            + sql_string(table)
            + " ORDER BY ordinal_position"
        )
    else:
        sql = (
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = "
            + sql_string(table)
            + " ORDER BY ordinal_position"
        )
    _columns, rows = await fetch_select(db, engine, sql)
    return [str(row[0]) for row in rows if row and row[0] is not None]


async def server_column_defs(
    db: DatabaseConnection, engine: str, table: str
) -> List[Dict[str, Any]]:
    """Column definitions for a PostgreSQL or MySQL CREATE TABLE."""
    if engine == "postgresql":
        where = "table_schema = 'public' AND table_name = " + sql_string(table)
    elif engine == "mysql":
        where = "table_schema = DATABASE() AND table_name = " + sql_string(
            table
        )
    else:
        raise ValueError("engine")
    sql = (
        "SELECT column_name, data_type, is_nullable, "
        "character_maximum_length, numeric_precision, numeric_scale "
        "FROM information_schema.columns WHERE "
        + where
        + " ORDER BY ordinal_position"
    )
    columns, rows = await fetch_select(db, engine, sql)
    index = {name.lower(): pos for pos, name in enumerate(columns)}
    defs: List[Dict[str, Any]] = []
    for row in rows:
        mapped = {
            name: row[pos] for name, pos in index.items() if pos < len(row)
        }
        typ = format_data_type(mapped)
        name = mapped.get("column_name")
        if not name or not typ:
            raise ValueError("column type cannot be copied without guessing")
        nullable = str(mapped.get("is_nullable", "YES")).upper() != "NO"
        defs.append({"name": str(name), "type": typ, "nullable": nullable})
    return defs


async def sqlite_create_sql(
    db: DatabaseConnection, table: str
) -> Optional[str]:
    """CREATE TABLE text from sqlite_master, or None when it is not usable."""
    sql = (
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = "
        + sql_string(table)
    )
    _columns, rows = await fetch_select(db, "sqlite", sql)
    if not rows or not rows[0] or not isinstance(rows[0][0], str):
        return None
    text = rows[0][0]
    if not acceptable_create(text):
        return None
    return text


async def count_rows(db: DatabaseConnection, engine: str, table: str) -> int:
    sql = f"SELECT COUNT(*) FROM {quote_ident(table, engine)}"
    _columns, rows = await fetch_select(db, engine, sql)
    if not rows or rows[0][0] is None:
        return 0
    return int(rows[0][0])


async def read_table(
    db: DatabaseConnection, engine: str, table: str
) -> Tuple[List[str], List[Row]]:
    sql = f"SELECT * FROM {quote_ident(table, engine)}"
    return await fetch_select(db, engine, sql)


async def write_table(
    db: DatabaseConnection,
    engine: str,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Row],
    *,
    create_sql: Optional[str] = None,
    delete_first: bool = False,
) -> None:
    """Create or fill ``table``. ``delete_first`` runs only after confirmation."""
    raw = getattr(db, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    qtable = quote_ident(table, engine)
    insert = None
    params: List[Row] = []
    if rows:
        if not columns:
            raise ValueError("columns")
        marks = ", ".join("?" if engine == "sqlite" else "%s" for _ in columns)
        quoted_cols = ", ".join(
            quote_ident(column, engine) for column in columns
        )
        insert = f"INSERT INTO {qtable} ({quoted_cols}) VALUES ({marks})"
        params = [tuple(_param(value) for value in row) for row in rows]
    if engine == "sqlite":
        try:
            if create_sql:
                await raw.execute(create_sql)
            if delete_first:
                await raw.execute(f"DELETE FROM {qtable}")
            if insert and params:
                await raw.executemany(insert, params)
            await raw.commit()
        except Exception:
            await rollback(db)
            raise
        return
    cursor = raw.cursor()
    try:
        if create_sql:
            cursor.execute(create_sql)
        if delete_first:
            cursor.execute(f"DELETE FROM {qtable}")
        if insert and params:
            cursor.executemany(insert, params)
        raw.commit()
    except Exception:
        await rollback(db)
        raise
    finally:
        cursor.close()


def _config_of(connection: Any) -> Optional[ConnectionConfig]:
    if isinstance(connection, ConnectionConfig):
        return connection
    config = getattr(connection, "config", None)
    if isinstance(config, ConnectionConfig):
        return config
    return None


def _collect_secret(found: List[str], value: Any) -> None:
    if isinstance(value, str) and len(value) >= 4 and value not in found:
        found.append(value)


def _param(value: Any) -> Any:
    if isinstance(value, memoryview):
        return bytes(value)
    return value
