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
            self.connection = psycopg2.connect(
                host=self.config.host or "localhost",
                port=self.config.port or 5432,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
            )
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from PostgreSQL database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze PostgreSQL storage"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        # Get table sizes
        cursor.execute("""
            SELECT 
                schemaname || '.' || tablename as name,
                pg_total_relation_size(schemaname || '.' || tablename) as size,
                pg_relation_size(schemaname || '.' || tablename) as table_size,
                (SELECT COUNT(*) FROM information_schema.tables 
                 WHERE table_schema = t.schemaname AND table_name = t.tablename) as row_count
            FROM pg_tables t
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY size DESC
        """)

        tables = []
        total_size = 0
        for row in cursor.fetchall():
            # Get actual row count
            cursor.execute(f'SELECT COUNT(*) FROM "{row["name"].split(".")[0]}"."{row["name"].split(".")[1]}"')
            row_count = cursor.fetchone()[0]

            table_size = row["table_size"] or 0
            index_size = (row["size"] or 0) - table_size

            tables.append({
                "name": row["name"],
                "size": table_size,
                "rowCount": row_count,
                "indexSize": index_size,
                "bloat": 0.0,
            })
            total_size += row["size"] or 0

        # Get indexes
        cursor.execute("""
            SELECT 
                schemaname || '.' || indexname as name,
                tablename as table_name,
                pg_relation_size(indexrelid) as size
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        """)

        indexes = []
        for row in cursor.fetchall():
            indexes.append({
                "name": row["name"],
                "tableName": row["table_name"],
                "size": row["size"] or 0,
                "bloat": 0.0,
            })

        largest_table = tables[0] if tables else {"name": "N/A", "size": 0, "rowCount": 0}

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
        cursor.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """)

        schemas = []
        for schema_row in cursor.fetchall():
            schema_name = schema_row["schema_name"]

            # Get tables
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s
            """, (schema_name,))

            tables = []
            for table_row in cursor.fetchall():
                table_name = table_row["table_name"]

                # Get columns
                cursor.execute("""
                    SELECT 
                        column_name,
                        data_type,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """, (schema_name, table_name))

                columns = []
                for col in cursor.fetchall():
                    columns.append({
                        "name": col["column_name"],
                        "type": col["data_type"],
                        "nullable": col["is_nullable"] == "YES",
                        "defaultValue": col["column_default"],
                    })

                # Get indexes
                cursor.execute("""
                    SELECT 
                        indexname,
                        indexdef
                    FROM pg_indexes
                    WHERE schemaname = %s AND tablename = %s
                """, (schema_name, table_name))

                indexes = []
                for idx in cursor.fetchall():
                    indexes.append({
                        "name": idx["indexname"],
                        "columns": [],
                        "unique": "UNIQUE" in idx["indexdef"].upper(),
                    })

                tables.append({
                    "name": table_name,
                    "columns": columns,
                    "indexes": indexes,
                })

            schemas.append({
                "name": schema_name,
                "tables": tables,
            })

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
            "--host", self.config.host or "localhost",
            "--port", str(self.config.port or 5432),
            "--username", self.config.username,
            "--dbname", self.config.database,
            "--format", "c",
            "--file", str(backup_file),
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

    async def restore_backup(self, backup_path: str) -> None:
        """Restore PostgreSQL backup using pg_restore"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Build pg_restore command
        cmd = [
            "pg_restore",
            "--host", self.config.host or "localhost",
            "--port", str(self.config.port or 5432),
            "--username", self.config.username,
            "--dbname", self.config.database,
            "--clean",
            "--if-exists",
            str(backup_file),
        ]

        # Set password via environment variable
        env = __import__("os").environ.copy()
        if self.config.password:
            env["PGPASSWORD"] = self.config.password

        # Run pg_restore
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"pg_restore failed: {stderr.decode()}")

