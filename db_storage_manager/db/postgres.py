"""
PostgreSQL database connection
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, List
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


class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None

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

    async def restore_backup(self, backup_path: str) -> None:
        """Restore PostgreSQL backup using pg_restore"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # pg_restore --clean cannot DROP a backed-up table while a table that
        # exists only on the target still references it. Drop each archived
        # table with CASCADE first: the foreign key goes away, the target-only
        # table stays. Views that depend on an archived table are dropped and
        # come back only when the backup contains them.
        listing = await self._pg_restore_list(backup_file)
        from psycopg2 import sql as pg_sql

        cursor = self.connection.cursor()
        try:
            for schema, table in pg_restore_table_idents(listing):
                cursor.execute(
                    pg_sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                        pg_sql.Identifier(schema), pg_sql.Identifier(table)
                    )
                )
            self.connection.commit()
        finally:
            cursor.close()

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
            str(backup_file),
        ]

        # Set password via environment variable
        env = __import__("os").environ.copy()
        if self.config.password:
            env["PGPASSWORD"] = self.config.password
        # Error text is parsed below; keep it in English.
        env["LC_MESSAGES"] = "C"

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
            if not pg_restore_only_version_skew(message):
                raise RuntimeError(f"pg_restore failed: {message}")
