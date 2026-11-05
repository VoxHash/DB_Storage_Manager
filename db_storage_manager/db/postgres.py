"""
PostgreSQL database connection
"""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


def quote_pg_ident(name: str) -> str:
    """Quote a PostgreSQL identifier. Rejects NUL."""
    if "\x00" in name:
        raise ValueError("identifier contains NUL")
    return '"' + name.replace('"', '""') + '"'


def pg_restore_table_idents(listing: str) -> list[tuple[str, str]]:
    """``(schema, table)`` pairs from ``pg_restore --list`` output.

    ``TABLE DATA`` lines are not tables. ``pg_catalog`` and
    ``information_schema`` are never returned.
    """
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in listing.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        _dump_id, sep, rest = line.partition(";")
        if not sep:
            continue
        tokens = _pg_toc_tokens(rest.strip())
        # catalogId, oid, description…, schema, name, owner.
        # Description may be several words ("TABLE DATA"). The last three
        # fields are schema, name and owner, and they may be quoted.
        if len(tokens) < 6:
            continue
        description = " ".join(tokens[2:-3])
        if description != "TABLE":
            continue
        schema, name = tokens[-3], tokens[-2]
        if schema in {"pg_catalog", "information_schema"}:
            continue
        key = (schema, name)
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def drop_table_cascade_sql(schema: str, table: str) -> str:
    """DROP that also removes foreign keys from tables the backup does not contain."""
    return (
        f"DROP TABLE IF EXISTS {quote_pg_ident(schema)}.{quote_pg_ident(table)} CASCADE"
    )


def _pg_toc_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
            continue
        if text[index] == '"':
            index += 1
            buf: list[str] = []
            while index < length:
                if text[index] == '"':
                    if index + 1 < length and text[index + 1] == '"':
                        buf.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                buf.append(text[index])
                index += 1
            tokens.append("".join(buf))
            continue
        start = index
        while index < length and not text[index].isspace():
            index += 1
        tokens.append(text[start:index])
    return tokens


def pg_restore_only_version_skew(stderr: str) -> bool:
    """True when every pg_restore error is a ``SET <parameter>`` the server lacks.

    A pg_restore newer than the server (for example client 18 into server 16)
    replays settings such as ``SET transaction_timeout = 0`` that older servers
    reject with "unrecognized configuration parameter". pg_restore then exits
    non-zero even though every object and row was restored. Any other error
    (permissions, missing roles, broken data) is still a failure.
    """
    error_lines = [
        line for line in stderr.splitlines() if line.startswith("pg_restore: error:")
    ]
    commands = [
        line for line in stderr.splitlines() if line.startswith("Command was:")
    ]
    if not error_lines or len(commands) != len(error_lines):
        return False
    return all(
        "unrecognized configuration parameter" in line for line in error_lines
    ) and all(line[len("Command was:") :].lstrip().startswith("SET ") for line in commands)


# pg_restore keeps going after a statement fails, then exits non-zero.
# These are the failures a hosted target (Supabase and the same pattern)
# raises for event triggers, the extensions schema, and the functions those
# triggers depend on. A table, row, or permission error is not in this set.
_PLATFORM_OWNER_PHRASES = (
    "must be owner of event trigger",
    "must be owner of function",
    "must be owner of procedure",
    "must be owner of aggregate",
    "must be owner of schema",
    "must be owner of extension",
)
_PLATFORM_DEPEND_PHRASES = (
    "cannot drop function ",
    "cannot drop procedure ",
    "cannot drop aggregate ",
    "cannot drop schema ",
    "cannot drop extension ",
    "cannot drop event trigger ",
)
_PLATFORM_EXISTS_KINDS = (
    'schema "',
    'function "',
    'procedure "',
    'aggregate "',
    'event trigger "',
    'extension "',
)


def _is_version_skew_error(error_line: str, command_line: Optional[str]) -> bool:
    if "unrecognized configuration parameter" not in error_line:
        return False
    if not command_line:
        return False
    return command_line[len("Command was:") :].lstrip().startswith("SET ")


def _is_platform_restore_error(line: str) -> bool:
    """True for one ``pg_restore: error:`` line about an unowned platform object."""
    text = line.lower()
    if any(phrase in text for phrase in _PLATFORM_OWNER_PHRASES):
        return True
    if "because other objects depend on it" in text and any(
        phrase in text for phrase in _PLATFORM_DEPEND_PHRASES
    ):
        return True
    if "already exists" in text and any(kind in text for kind in _PLATFORM_EXISTS_KINDS):
        return True
    return False


def _is_skippable_acl_error(error_line: str, command_line: Optional[str]) -> bool:
    """GRANT OPTION loops and default privileges for a role the session is not.

    These are ACL statements. A table or row permission error is not in this
    set, so a failed ``COPY`` still fails the restore.
    """
    text = error_line.lower()
    grant_loop = "grant options cannot be granted back to your own grantor" in text
    default_priv = "permission denied to change default privileges" in text
    if not grant_loop and not default_priv:
        return False
    if command_line is None:
        return True
    command = command_line[len("Command was:") :].lstrip().upper()
    if grant_loop and not command.startswith("GRANT "):
        return False
    if default_priv and not command.startswith("ALTER DEFAULT PRIVILEGES"):
        return False
    return True


def pg_restore_errors_tolerated(stderr: str) -> bool:
    """True when every pg_restore error is version skew, an unowned platform object, or an ACL the session cannot apply.

    ``pg_restore`` applies the rest of the archive after these statements fail.
    ``must be owner of table`` and ``relation already exists`` still fail the
    restore: those mean application data was not replaced.
    """
    error_lines = [
        line for line in stderr.splitlines() if line.startswith("pg_restore: error:")
    ]
    if not error_lines:
        return False
    commands = [
        line for line in stderr.splitlines() if line.startswith("Command was:")
    ]
    paired = len(commands) == len(error_lines)
    for index, line in enumerate(error_lines):
        command = commands[index] if paired else None
        if _is_platform_restore_error(line):
            continue
        if _is_version_skew_error(line, command):
            continue
        if _is_skippable_acl_error(line, command):
            continue
        return False
    return True


def pg_restore_stderr_has_platform_object_errors(stderr: str) -> bool:
    return any(
        _is_platform_restore_error(line)
        for line in stderr.splitlines()
        if line.startswith("pg_restore: error:")
    )


def pg_restore_stderr_has_skipped_acl(stderr: str) -> bool:
    return any(
        _is_skippable_acl_error(line, None)
        for line in stderr.splitlines()
        if line.startswith("pg_restore: error:")
    )


_CATALOG_SCHEMAS = {"pg_catalog", "information_schema"}
_ACL_SKIP_NOTE = "Skipped ACLs the session cannot apply."


def _entry_acl_blocked(
    entry: dict,
    blocked_acl_roles: set[str],
    skip_catalog_acl: bool,
) -> bool:
    """DEFAULT ACL for another role, or an ACL on a catalog schema."""
    description = entry["description"]
    if description == "DEFAULT ACL":
        owner = entry.get("owner") or ""
        return bool(owner) and owner in blocked_acl_roles
    if (
        skip_catalog_acl
        and description == "ACL"
        and entry["schema"] in _CATALOG_SCHEMAS
    ):
        return True
    return False


# Longest descriptions first so "TABLE DATA" is not parsed as "TABLE".
_TOC_DESCRIPTIONS: tuple[str, ...] = (
    "MATERIALIZED VIEW DATA",
    "TEXT SEARCH CONFIGURATION",
    "TEXT SEARCH DICTIONARY",
    "TEXT SEARCH TEMPLATE",
    "TEXT SEARCH PARSER",
    "FOREIGN DATA WRAPPER",
    "SEQUENCE OWNED BY",
    "PROCEDURAL LANGUAGE",
    "DATABASE PROPERTIES",
    "PUBLICATION TABLES",
    "MATERIALIZED VIEW",
    "CHECK CONSTRAINT",
    "OPERATOR FAMILY",
    "OPERATOR CLASS",
    "FK CONSTRAINT",
    "EVENT TRIGGER",
    "ACCESS METHOD",
    "BLOB COMMENTS",
    "ACL LANGUAGE",
    "USER MAPPING",
    "ROW SECURITY",
    "INDEX ATTACH",
    "DEFAULT ACL",
    "SEQUENCE SET",
    "LARGE OBJECT",
    "TABLE DATA",
    "CONSTRAINT",
    "PUBLICATION",
    "SUBSCRIPTION",
    "AGGREGATE",
    "PROCEDURE",
    "EXTENSION",
    "COLLATION",
    "CONVERSION",
    "SHELL TYPE",
    "FUNCTION",
    "SEQUENCE",
    "TRIGGER",
    "COMMENT",
    "LANGUAGE",
    "OPERATOR",
    "DATABASE",
    "STATISTICS",
    "TRANSFORM",
    "SCHEMA",
    "POLICY",
    "DOMAIN",
    "SERVER",
    "TABLE",
    "INDEX",
    "RULE",
    "VIEW",
    "TYPE",
    "CAST",
    "BLOB",
    "BLOBS",
    "GRANT",
    "DEFAULT",
    "ACL",
)

# TOC lines whose schema field is "-" carry the real name in the tag:
# "EXTENSION pg_trgm", "SCHEMA auth".
_DASH_TAG_KINDS = {"SCHEMA", "EXTENSION", "LANGUAGE", "DATABASE"}


def parse_pg_restore_toc_entry(line: str) -> Optional[dict]:
    """One ``pg_restore --list`` entry, or None for a header / comment.

    ``tag`` is the object name split on whitespace after the schema. A
    constraint tag is ``table constraint`` on pg_dump 17+ and only the
    constraint name on older archives. An empty owner (a trailing space in
    the listing) leaves the name as the last token.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(";"):
        return None
    dump_id, sep, rest = stripped.partition(";")
    if not sep or not dump_id.strip().isdigit():
        return None
    tokens = _pg_toc_tokens(rest.strip())
    if len(tokens) < 4:
        return None
    body = tokens[2:]
    for desc in _TOC_DESCRIPTIONS:
        desc_tokens = desc.split(" ")
        width = len(desc_tokens)
        if body[:width] != desc_tokens:
            continue
        tail = body[width:]
        if len(tail) < 2:
            return None
        schema = tail[0]
        payload = tail[1:]
        owner = ""
        if len(payload) >= 2:
            owner = payload[-1]
            tag = payload[:-1]
            if (
                schema == "-"
                and len(tag) == 1
                and tag[0] in _DASH_TAG_KINDS
            ):
                # Trailing space in the listing: the last token is the name,
                # not an owner.
                tag = payload
                owner = ""
        else:
            tag = payload
        if not tag:
            return None
        return {
            "description": desc,
            "schema": schema,
            "tag": tag,
            "owner": owner,
        }
    return None


def _token_is_routine(token: str, names: set) -> bool:
    """True when ``token`` is ``name`` or ``name(arg types)`` for a blocked routine."""
    if "(" not in token:
        return False
    return token.split("(", 1)[0] in names


def _toc_line_blocked(
    line: str,
    blocked_schemas: set[str],
    blocked_names: Dict[str, set],
    blocked_extensions: set[str],
    blocked_event_triggers: Optional[set[str]] = None,
    blocked_routines: Optional[Dict[str, set]] = None,
    blocked_schema_defs: Optional[set[str]] = None,
    blocked_acl_roles: Optional[set[str]] = None,
    skip_catalog_acl: bool = False,
) -> bool:
    entry = parse_pg_restore_toc_entry(line)
    if entry is None:
        return False
    if _entry_acl_blocked(entry, blocked_acl_roles or set(), skip_catalog_acl):
        return True
    schema = entry["schema"]
    tag: List[str] = entry["tag"]
    description = entry["description"]
    event_triggers = blocked_event_triggers or set()
    routines = blocked_routines or {}
    schema_defs = blocked_schema_defs or set()
    if schema in blocked_schemas:
        return True
    if description == "SCHEMA" and tag[0] in blocked_schemas:
        return True
    if description == "SCHEMA" and tag[0] in schema_defs:
        return True
    if description == "EXTENSION" and tag[0] in blocked_extensions:
        return True
    if description == "EVENT TRIGGER" and tag[0] in event_triggers:
        return True
    if schema == "-" and len(tag) >= 2:
        if tag[0] == "SCHEMA" and (
            tag[1] in blocked_schemas or tag[1] in schema_defs
        ):
            return True
        if tag[0] == "EXTENSION" and tag[1] in blocked_extensions:
            return True
    if (
        event_triggers
        and schema == "-"
        and description in {"COMMENT", "ACL"}
        and "EVENT" in tag
        and "TRIGGER" in tag
        and any(token in event_triggers for token in tag)
    ):
        return True
    routine_names = routines.get(schema)
    if routine_names and description in {"FUNCTION", "PROCEDURE", "AGGREGATE", "COMMENT", "ACL"}:
        if any(_token_is_routine(token, routine_names) for token in tag):
            return True
    names = blocked_names.get(schema)
    if names and any(token in names for token in tag):
        return True
    return False


def filter_pg_restore_list(
    listing: str,
    blocked_schemas: set[str],
    blocked_names: Dict[str, set],
    blocked_extensions: set[str],
    blocked_event_triggers: Optional[set[str]] = None,
    blocked_routines: Optional[Dict[str, set]] = None,
    blocked_schema_defs: Optional[set[str]] = None,
    blocked_acl_roles: Optional[set[str]] = None,
    skip_catalog_acl: bool = False,
) -> str:
    """Comment out TOC entries the session must not drop or replace.

    ``pg_restore --use-list`` skips lines that start with ``;``. Schemas the
    session cannot create in (hosted ``auth``, ``storage``, and the same
    pattern elsewhere) are removed whole. Individual relations the session
    cannot drop, and extensions it cannot drop, are removed too. Event
    triggers, functions, and ``CREATE/DROP SCHEMA`` for schemas the session
    does not own are removed as well. Their dependents are not dropped with
    ``CASCADE``. ``DEFAULT ACL`` entries for a role the session is not a
    member of, and ``ACL`` entries in ``pg_catalog`` / ``information_schema``,
    are removed too: those are the GRANT OPTION loops and
    ``ALTER DEFAULT PRIVILEGES FOR ROLE`` statements a hosted restore cannot
    apply. Everything else is unchanged.
    """
    event_triggers = blocked_event_triggers or set()
    routines = blocked_routines or {}
    schema_defs = blocked_schema_defs or set()
    acl_roles = blocked_acl_roles or set()
    if (
        not blocked_schemas
        and not blocked_names
        and not blocked_extensions
        and not event_triggers
        and not any(routines.values())
        and not schema_defs
        and not acl_roles
        and not skip_catalog_acl
    ):
        return listing
    lines = []
    for raw in listing.splitlines():
        if _toc_line_blocked(
            raw,
            blocked_schemas,
            blocked_names,
            blocked_extensions,
            event_triggers,
            routines,
            schema_defs,
            acl_roles,
            skip_catalog_acl,
        ):
            lines.append(";" + raw)
        else:
            lines.append(raw)
    text = "\n".join(lines)
    if listing.endswith("\n"):
        text += "\n"
    return text


def _acl_skip_sentence(
    listing: str,
    blocked_acl_roles: set[str],
    skip_catalog_acl: bool,
) -> Optional[str]:
    """One sentence when default-privilege or catalog ACL lines were skipped."""
    if not blocked_acl_roles and not skip_catalog_acl:
        return None
    roles: list[str] = []
    catalog = False
    for raw in listing.splitlines():
        entry = parse_pg_restore_toc_entry(raw)
        if entry is None:
            continue
        if not _entry_acl_blocked(entry, blocked_acl_roles, skip_catalog_acl):
            continue
        if entry["description"] == "DEFAULT ACL":
            owner = entry.get("owner") or ""
            if owner:
                roles.append(owner)
        elif entry["description"] == "ACL":
            catalog = True
    unique = sorted(dict.fromkeys(roles))
    bits: list[str] = []
    if unique:
        if len(unique) <= 3:
            bits.append("default privileges for " + ", ".join(unique))
        else:
            bits.append(f"default privileges for {len(unique)} roles")
    if catalog:
        bits.append("catalog grants")
    if not bits:
        return None
    return _ACL_SKIP_NOTE.rstrip(".") + ": " + "; ".join(bits) + "."


def platform_skip_notice(
    listing: str,
    blocked_schemas: set[str],
    blocked_names: Dict[str, set],
    blocked_extensions: set[str],
    blocked_event_triggers: Optional[set[str]] = None,
    blocked_routines: Optional[Dict[str, set]] = None,
    blocked_schema_defs: Optional[set[str]] = None,
    blocked_acl_roles: Optional[set[str]] = None,
    skip_catalog_acl: bool = False,
) -> Optional[str]:
    """One sentence naming platform objects removed from this restore list."""
    event_triggers = blocked_event_triggers or set()
    routines = blocked_routines or {}
    schema_defs = blocked_schema_defs or set()
    acl_roles = blocked_acl_roles or set()
    events: list[str] = []
    schemas: list[str] = []
    functions: list[str] = []
    extensions: list[str] = []
    for raw in listing.splitlines():
        entry = parse_pg_restore_toc_entry(raw)
        if entry is None:
            continue
        if not _toc_line_blocked(
            raw,
            blocked_schemas,
            blocked_names,
            blocked_extensions,
            event_triggers,
            routines,
            schema_defs,
            acl_roles,
            skip_catalog_acl,
        ):
            continue
        description = entry["description"]
        schema = entry["schema"]
        tag: List[str] = entry["tag"]
        if not tag:
            continue
        if description == "EVENT TRIGGER":
            events.append(tag[0])
        elif description == "SCHEMA":
            schemas.append(tag[0])
        elif description == "EXTENSION":
            extensions.append(tag[0])
        elif description in {"FUNCTION", "PROCEDURE", "AGGREGATE"}:
            if schema in blocked_schemas:
                continue
            functions.append(
                f"{schema}.{tag[0].split('(', 1)[0]}"
                if schema != "-"
                else tag[0].split("(", 1)[0]
            )

    def clause(label: str, names: list[str]) -> Optional[str]:
        unique = sorted(dict.fromkeys(names))
        if not unique:
            return None
        if len(unique) <= 4:
            return label + " " + ", ".join(unique)
        head = ", ".join(unique[:3])
        return f"{label} ({len(unique)}) {head}, …"

    parts = [
        part
        for part in (
            clause("event triggers", events),
            clause("schemas", schemas),
            clause("functions", functions),
            clause("extensions", extensions),
        )
        if part
    ]
    acl_sentence = _acl_skip_sentence(listing, acl_roles, skip_catalog_acl)
    if not parts and not acl_sentence:
        return None
    text = ""
    if parts:
        text = (
            "Platform objects this session cannot replace were left in place: "
            + "; ".join(parts)
            + "."
        )
    if acl_sentence:
        text = (text + " " + acl_sentence).strip()
    return text


class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None
        self.restore_notice: Optional[str] = None

    async def connect(self) -> None:
        """Connect to PostgreSQL database"""
        if self.config.connection_string:
            self.connection = psycopg2.connect(self.config.connection_string)
        else:
            from ..cloud.connect_auth import resolve_password_and_ssl

            password, ssl_kwargs = resolve_password_and_ssl(self.config)
            connect_kwargs = {
                "host": self.config.host or "localhost",
                "port": self.config.port or 5432,
                "database": self.config.database,
                "user": self.config.username,
                "password": password,
            }
            if ssl_kwargs.get("sslmode"):
                connect_kwargs["sslmode"] = ssl_kwargs["sslmode"]
            if ssl_kwargs.get("sslrootcert"):
                connect_kwargs["sslrootcert"] = ssl_kwargs["sslrootcert"]
            self.connection = psycopg2.connect(**connect_kwargs)
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from PostgreSQL database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze PostgreSQL storage via pg_catalog discovery only.

        Never issues per-table ``COUNT(*)`` or hardcoded relation names — sizes
        and row estimates come from ``pg_class`` OIDs that currently exist.
        """
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        # Ordinary / partitioned / materialized relations only (no views)
        cursor.execute(
            """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                pg_total_relation_size(c.oid) AS total_size,
                pg_relation_size(c.oid) AS table_size,
                GREATEST(COALESCE(c.reltuples, 0), 0)::bigint AS row_estimate
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'm')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND n.nspname NOT LIKE 'pg_temp_%'
              AND n.nspname NOT LIKE 'pg_toast_temp_%'
            ORDER BY total_size DESC NULLS LAST
            """
        )

        tables = []
        total_size = 0
        for row in cursor.fetchall():
            schema_name = row["schema_name"]
            table_name = row["table_name"]
            table_size = int(row["table_size"] or 0)
            relation_total = int(row["total_size"] or 0)
            index_size = max(relation_total - table_size, 0)
            row_count = int(row["row_estimate"] or 0)

            tables.append(
                {
                    "name": f"{schema_name}.{table_name}",
                    "size": table_size,
                    "rowCount": row_count,
                    "indexSize": index_size,
                    "bloat": 0.0,
                }
            )
            total_size += relation_total

        cursor.execute(
            """
            SELECT
                n.nspname || '.' || c.relname AS name,
                t.relname AS table_name,
                pg_relation_size(c.oid) AS size
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid
            JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
            WHERE c.relkind = 'i'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND n.nspname NOT LIKE 'pg_temp_%'
              AND n.nspname NOT LIKE 'pg_toast_temp_%'
            ORDER BY size DESC NULLS LAST
            """
        )

        indexes = []
        for row in cursor.fetchall():
            indexes.append(
                {
                    "name": row["name"],
                    "tableName": row["table_name"],
                    "size": int(row["size"] or 0),
                    "bloat": 0.0,
                }
            )

        largest_table = (
            tables[0] if tables else {"name": "N/A", "size": 0, "rowCount": 0}
        )

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": len(indexes),
            "largestTable": largest_table,
            "tables": tables,
            "indexes": indexes,
            "lastAnalyzed": __import__("datetime").datetime.now().isoformat(),
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute a PostgreSQL query"""
        if not self.connection:
            await self.connect()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        import time

        start_time = time.time()

        try:
            cursor.execute(query)
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                columns = ["affected_rows"]
                rows = [{"affected_rows": cursor.rowcount}]

            execution_time = int((time.time() - start_time) * 1000)

            # Get explain plan for SELECT queries
            explain_plan = None
            if query.strip().upper().startswith("SELECT"):
                try:
                    cursor.execute(f"EXPLAIN {query}")
                    explain_plan = [row[0] for row in cursor.fetchall()]
                except Exception:
                    pass

            return {
                "columns": columns,
                "rows": rows,
                "rowCount": len(rows),
                "executionTime": execution_time,
                "explainPlan": explain_plan,
            }
        finally:
            cursor.close()

    async def get_schema(self) -> SchemaInfo:
        """Get PostgreSQL schema"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        # Get schemas
        cursor.execute(
            """
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """
        )

        schemas = []
        for schema_row in cursor.fetchall():
            schema_name = schema_row["schema_name"]

            # Get tables
            cursor.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s
            """,
                (schema_name,),
            )

            tables = []
            for table_row in cursor.fetchall():
                table_name = table_row["table_name"]

                # Get columns
                cursor.execute(
                    """
                    SELECT 
                        column_name,
                        data_type,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """,
                    (schema_name, table_name),
                )

                columns = []
                for col in cursor.fetchall():
                    columns.append(
                        {
                            "name": col["column_name"],
                            "type": col["data_type"],
                            "nullable": col["is_nullable"] == "YES",
                            "defaultValue": col["column_default"],
                        }
                    )

                # Get indexes
                cursor.execute(
                    """
                    SELECT 
                        indexname,
                        indexdef
                    FROM pg_indexes
                    WHERE schemaname = %s AND tablename = %s
                """,
                    (schema_name, table_name),
                )

                indexes = []
                for idx in cursor.fetchall():
                    indexes.append(
                        {
                            "name": idx["indexname"],
                            "columns": [],
                            "unique": "UNIQUE" in idx["indexdef"].upper(),
                        }
                    )

                tables.append(
                    {
                        "name": table_name,
                        "columns": columns,
                        "indexes": indexes,
                    }
                )

            schemas.append(
                {
                    "name": schema_name,
                    "tables": tables,
                }
            )

        return {"schemas": schemas}

    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create PostgreSQL backup using pg_dump"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # Build pg_dump command
        cmd = [
            "pg_dump",
            "--host",
            self.config.host or "localhost",
            "--port",
            str(self.config.port or 5432),
            "--username",
            self.config.username,
            "--dbname",
            self.config.database,
            "--format",
            "c",
            "--file",
            str(backup_file),
        ]

        # Set password via environment variable
        env = __import__("os").environ.copy()
        if self.config.password:
            env["PGPASSWORD"] = self.config.password

        # Run pg_dump
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

        size = backup_file.stat().st_size
        return {"path": str(backup_file), "size": size}

    async def _pg_restore_list(self, backup_file: Path) -> str:
        process = await asyncio.create_subprocess_exec(
            "pg_restore",
            "--list",
            str(backup_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip() or "pg_restore --list failed"
            raise RuntimeError(detail)
        return stdout.decode(errors="replace")

    def _session_restore_blocks(self) -> dict:
        """Objects this session must not drop or replace during restore.

        A schema is blocked whole when it already exists, the session is not
        a member of the owning role, and it cannot ``CREATE`` there. That is
        how hosted Postgres (Supabase ``auth`` / ``storage``, and the same
        pattern elsewhere) rejects ``DROP TABLE audit_log_entries``. Tables
        the session does own are not blocked, so ``CASCADE`` still runs for
        them. Names include indexes, constraints and triggers of blocked
        relations so both old and pg_dump 17+ TOC tags match.

        Event triggers, functions, and the schema entry itself are separate.
        On a hosted database the connecting role often has ``CREATE`` on
        ``extensions`` (so the schema is not blocked whole) and still cannot
        own the event triggers or the functions they call. Those statements
        are omitted. Nothing here is dropped with ``CASCADE``.
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT n.nspname,
                       has_schema_privilege(n.oid, 'CREATE')
                FROM pg_namespace n
                WHERE n.nspname NOT IN (
                    'pg_catalog', 'information_schema', 'pg_toast'
                )
                  AND n.nspname NOT LIKE 'pg_temp_%'
                  AND n.nspname NOT LIKE 'pg_toast_temp_%'
                  AND NOT pg_has_role(current_user, n.nspowner, 'MEMBER')
                """
            )
            unowned_schemas: set[str] = set()
            schemas: set[str] = set()
            for name, can_create in cursor.fetchall():
                unowned_schemas.add(name)
                if not can_create:
                    schemas.add(name)

            cursor.execute(
                """
                SELECT n.nspname, c.relname, c.relkind
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'i', 'I', 'f')
                  AND n.nspname NOT IN (
                      'pg_catalog', 'information_schema', 'pg_toast'
                  )
                  AND n.nspname NOT LIKE 'pg_temp_%'
                  AND n.nspname NOT LIKE 'pg_toast_temp_%'
                  AND NOT pg_has_role(current_user, c.relowner, 'MEMBER')
                """
            )
            tables: set[tuple[str, str]] = set()
            names: Dict[str, set] = {}
            for schema, name, relkind in cursor.fetchall():
                names.setdefault(schema, set()).add(name)
                if relkind in ("r", "p"):
                    tables.add((schema, name))

            cursor.execute(
                """
                SELECT n.nspname, con.conname
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN (
                    'pg_catalog', 'information_schema', 'pg_toast'
                )
                  AND NOT pg_has_role(current_user, c.relowner, 'MEMBER')
                """
            )
            for schema, name in cursor.fetchall():
                names.setdefault(schema, set()).add(name)

            cursor.execute(
                """
                SELECT n.nspname, t.tgname
                FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE NOT t.tgisinternal
                  AND n.nspname NOT IN (
                      'pg_catalog', 'information_schema', 'pg_toast'
                  )
                  AND NOT pg_has_role(current_user, c.relowner, 'MEMBER')
                """
            )
            for schema, name in cursor.fetchall():
                names.setdefault(schema, set()).add(name)

            cursor.execute(
                """
                SELECT extname
                FROM pg_extension
                WHERE NOT pg_has_role(current_user, extowner, 'MEMBER')
                """
            )
            extensions = {row[0] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT evtname
                FROM pg_event_trigger
                WHERE NOT pg_has_role(current_user, evtowner, 'MEMBER')
                """
            )
            event_triggers = {row[0] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT n.nspname, p.proname
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname NOT IN (
                    'pg_catalog', 'information_schema', 'pg_toast'
                )
                  AND n.nspname NOT LIKE 'pg_temp_%'
                  AND n.nspname NOT LIKE 'pg_toast_temp_%'
                  AND (
                    NOT pg_has_role(current_user, p.proowner, 'MEMBER')
                    OR EXISTS (
                        SELECT 1
                        FROM pg_depend d
                        JOIN pg_event_trigger e ON e.oid = d.objid
                        WHERE d.classid = 'pg_event_trigger'::regclass
                          AND d.refclassid = 'pg_proc'::regclass
                          AND d.refobjid = p.oid
                          AND d.deptype = 'n'
                          AND NOT pg_has_role(current_user, e.evtowner, 'MEMBER')
                    )
                  )
                """
            )
            routines: Dict[str, set] = {}
            for schema, name in cursor.fetchall():
                routines.setdefault(schema, set()).add(name)

            cursor.execute(
                """
                SELECT rolname
                FROM pg_roles
                WHERE NOT pg_has_role(current_user, oid, 'MEMBER')
                """
            )
            acl_roles = {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()
        stuck = set(names) | set(routines)
        schema_defs = (unowned_schemas - schemas) | (stuck - schemas)
        return {
            "schemas": schemas,
            "tables": tables,
            "names": names,
            "extensions": extensions,
            "event_triggers": event_triggers,
            "routines": routines,
            "schema_defs": schema_defs,
            "acl_roles": acl_roles,
        }

    async def restore_backup(self, backup_path: str) -> None:
        """Restore PostgreSQL backup using pg_restore"""
        if not self.connection:
            await self.connect()
        self.restore_notice = None

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # pg_restore --clean cannot DROP a backed-up table while a table that
        # exists only on the target still references it. Drop each archived
        # table the session owns with CASCADE first: the foreign key goes
        # away, the target-only table stays. Views that depend on an archived
        # table are dropped and come back only when the backup contains them.
        # Tables in a schema the session cannot create in (and any other
        # table it does not own) are left untouched. Dropping them is what
        # raises "must be owner of table ...".
        listing = await self._pg_restore_list(backup_file)
        blocks = self._session_restore_blocks()
        blocked_schemas = blocks["schemas"]
        blocked_tables = blocks["tables"]
        blocked_names = blocks["names"]
        blocked_extensions = blocks["extensions"]
        blocked_event_triggers = blocks["event_triggers"]
        blocked_routines = blocks["routines"]
        blocked_schema_defs = blocks["schema_defs"]
        blocked_acl_roles = blocks["acl_roles"]
        from psycopg2 import sql as pg_sql

        cursor = self.connection.cursor()
        try:
            for schema, table in pg_restore_table_idents(listing):
                if schema in blocked_schemas or (schema, table) in blocked_tables:
                    continue
                cursor.execute(
                    pg_sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                        pg_sql.Identifier(schema), pg_sql.Identifier(table)
                    )
                )
            self.connection.commit()
        finally:
            cursor.close()

        filtered = filter_pg_restore_list(
            listing,
            blocked_schemas,
            blocked_names,
            blocked_extensions,
            blocked_event_triggers,
            blocked_routines,
            blocked_schema_defs,
            blocked_acl_roles,
            True,
        )
        self.restore_notice = platform_skip_notice(
            listing,
            blocked_schemas,
            blocked_names,
            blocked_extensions,
            blocked_event_triggers,
            blocked_routines,
            blocked_schema_defs,
            blocked_acl_roles,
            True,
        )
        list_path: Optional[Path] = None
        if filtered != listing:
            fd, name = tempfile.mkstemp(prefix="dsm-pg-restore-", suffix=".list")
            os.close(fd)
            list_path = Path(name)
            list_path.write_text(filtered, encoding="utf-8")

        # Build pg_restore command
        cmd = [
            "pg_restore",
            "--host",
            self.config.host or "localhost",
            "--port",
            str(self.config.port or 5432),
            "--username",
            self.config.username,
            "--dbname",
            self.config.database,
            "--clean",
            "--if-exists",
        ]
        if list_path is not None:
            # The archive still says OWNER TO for roles this session cannot
            # become (supabase_admin and the same pattern). Skipping those
            # commands keeps the tables we do restore from failing the run.
            cmd.append("--no-owner")
            cmd.extend(["--use-list", str(list_path)])
        cmd.append(str(backup_file))

        # Set password via environment variable
        env = os.environ.copy()
        if self.config.password:
            env["PGPASSWORD"] = self.config.password
        # Error text is parsed below; keep it in English.
        env["LC_MESSAGES"] = "C"

        try:
            # Run pg_restore
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                message = stderr.decode(errors="replace")
                if not pg_restore_errors_tolerated(message):
                    raise RuntimeError(f"pg_restore failed: {message}")
                if (
                    not self.restore_notice
                    and pg_restore_stderr_has_platform_object_errors(message)
                ):
                    self.restore_notice = (
                        "Platform objects this session cannot replace "
                        "were left in place."
                    )
                if pg_restore_stderr_has_skipped_acl(message):
                    if not self.restore_notice:
                        self.restore_notice = _ACL_SKIP_NOTE
                    elif "Skipped ACLs" not in self.restore_notice:
                        self.restore_notice = (
                            f"{self.restore_notice} {_ACL_SKIP_NOTE}"
                        )
        finally:
            if list_path is not None:
                list_path.unlink(missing_ok=True)
