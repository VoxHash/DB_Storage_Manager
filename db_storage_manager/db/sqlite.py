"""
SQLite database connection
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, List
import aiosqlite

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class SQLiteConnection(DatabaseConnection):
    """SQLite database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None

    async def connect(self) -> None:
        """Connect to SQLite database"""
        db_path = self.config.database or self.config.connection_string
        if not db_path:
            raise ValueError("SQLite database path is required")

        self.connection = await aiosqlite.connect(db_path)
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from SQLite database"""
        if self.connection:
            await self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze SQLite storage"""
        if not self.connection:
            await self.connect()

        # Get tables
        cursor = await self.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        )

        tables = []
        total_size = 0
        db_path = Path(self.config.database or self.config.connection_string)
        db_size = db_path.stat().st_size if db_path.exists() else 0

        table_rows = await cursor.fetchall()
        table_count = len(table_rows)

        for (table_name,) in table_rows:
            # Get row count
            count_cursor = await self.connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            )
            row_count = (await count_cursor.fetchone())[0]

            # Approximate table size (distribute total DB size)
            table_size = db_size // table_count if table_count > 0 else 0

            tables.append(
                {
                    "name": table_name,
                    "size": table_size,
                    "rowCount": row_count,
                    "indexSize": 0,
                    "bloat": 0.0,
                }
            )
            total_size += table_size

        # Get indexes
        cursor = await self.connection.execute(
            """
            SELECT name, tbl_name
            FROM sqlite_master
            WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        )

        indexes = []
        for index_name, table_name in await cursor.fetchall():
            indexes.append(
                {
                    "name": index_name,
                    "tableName": table_name,
                    "size": 0,
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
        """Execute a SQLite query"""
        if not self.connection:
            await self.connect()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        import time

        start_time = time.time()

        try:
            cursor = await self.connection.execute(query)
            rows = await cursor.fetchall()

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows_dict = [dict(zip(columns, row)) for row in rows]
            else:
                columns = ["affected_rows"]
                rows_dict = [{"affected_rows": self.connection.total_changes}]

            execution_time = int((time.time() - start_time) * 1000)

            # Get explain plan for SELECT queries
            explain_plan = None
            if query.strip().upper().startswith("SELECT"):
                try:
                    explain_cursor = await self.connection.execute(
                        f"EXPLAIN QUERY PLAN {query}"
                    )
                    explain_plan = await explain_cursor.fetchall()
                except Exception:
                    pass

            return {
                "columns": columns,
                "rows": rows_dict,
                "rowCount": len(rows_dict),
                "executionTime": execution_time,
                "explainPlan": explain_plan,
            }
        except Exception as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")

    async def get_schema(self) -> SchemaInfo:
        """Get SQLite schema"""
        if not self.connection:
            await self.connect()

        # Get tables
        cursor = await self.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        )

        tables = []
        for (table_name,) in await cursor.fetchall():
            # Get columns using PRAGMA
            pragma_cursor = await self.connection.execute(
                f"PRAGMA table_info({table_name})"
            )
            columns_data = await pragma_cursor.fetchall()

            columns = []
            for col in columns_data:
                columns.append(
                    {
                        "name": col[1],  # column name
                        "type": col[2],  # data type
                        "nullable": col[3] == 0,  # not null flag
                        "defaultValue": col[4],  # default value
                    }
                )

            # Get indexes
            index_cursor = await self.connection.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_%'
            """,
                (table_name,),
            )

            indexes = []
            for index_name, index_sql in await index_cursor.fetchall():
                indexes.append(
                    {
                        "name": index_name,
                        "columns": [],
                        "unique": "UNIQUE" in (index_sql or "").upper(),
                    }
                )

            tables.append(
                {
                    "name": table_name,
                    "columns": columns,
                    "indexes": indexes,
                }
            )

        return {
            "schemas": [
                {
                    "name": self.config.database or "default",
                    "tables": tables,
                }
            ]
        }

    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create SQLite backup"""
        if not self.connection:
            await self.connect()

        db_path = Path(self.config.database or self.config.connection_string)
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # Copy database file
        shutil.copy2(db_path, backup_file)
        size = backup_file.stat().st_size

        return {"path": str(backup_file), "size": size}

    async def restore_backup(self, backup_path: str) -> None:
        """Restore SQLite backup"""
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        db_path = Path(self.config.database or self.config.connection_string)

        # Disconnect before restoring
        await self.disconnect()

        # Copy backup file to database location
        shutil.copy2(backup_file, db_path)

        # Reconnect
        await self.connect()
