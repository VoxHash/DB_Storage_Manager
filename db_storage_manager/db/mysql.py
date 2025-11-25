"""
MySQL/MariaDB database connection
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pymysql
from pymysql.cursors import DictCursor

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class MySQLConnection(DatabaseConnection):
    """MySQL/MariaDB database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None

    async def connect(self) -> None:
        """Connect to MySQL database"""
        if self.config.connection_string:
            self.connection = pymysql.connect(
                host=self.config.host or "localhost",
                port=self.config.port or 3306,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
            )
        else:
            self.connection = pymysql.connect(
                host=self.config.host or "localhost",
                port=self.config.port or 3306,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
            )
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from MySQL database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze MySQL storage"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor(DictCursor)

        # Get table sizes
        cursor.execute("""
            SELECT 
                table_schema,
                table_name,
                data_length + index_length as total_size,
                data_length as table_size,
                index_length as index_size,
                table_rows as row_count
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY total_size DESC
        """, (self.config.database,))

        tables = []
        total_size = 0
        for row in cursor.fetchall():
            table_name = f"{row['table_schema']}.{row['table_name']}"
            table_size = int(row["table_size"] or 0)
            index_size = int(row["index_size"] or 0)
            row_count = int(row["row_count"] or 0)

            tables.append({
                "name": table_name,
                "size": table_size,
                "rowCount": row_count,
                "indexSize": index_size,
                "bloat": 0.0,
            })
            total_size += int(row["total_size"] or 0)

        # Get indexes
        cursor.execute("""
            SELECT 
                index_name,
                table_name,
                SUM(index_length) as size
            FROM information_schema.statistics
            WHERE table_schema = %s
            GROUP BY index_name, table_name
        """, (self.config.database,))

        indexes = []
        for row in cursor.fetchall():
            indexes.append({
                "name": row["index_name"],
                "tableName": row["table_name"],
                "size": int(row["size"] or 0),
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
        """Execute a MySQL query"""
        if not self.connection:
            await self.connect()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        cursor = self.connection.cursor(DictCursor)
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
                    explain_plan = [dict(row) for row in cursor.fetchall()]
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
        """Get MySQL schema"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor(DictCursor)

        # Get tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """, (self.config.database,))

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
            """, (self.config.database, table_name))

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
                    index_name,
                    non_unique,
                    column_name
                FROM information_schema.statistics
                WHERE table_schema = %s AND table_name = %s
            """, (self.config.database, table_name))

            indexes_dict = {}
            for idx in cursor.fetchall():
                idx_name = idx["index_name"]
                if idx_name not in indexes_dict:
                    indexes_dict[idx_name] = {
                        "name": idx_name,
                        "columns": [],
                        "unique": idx["non_unique"] == 0,
                    }
                indexes_dict[idx_name]["columns"].append(idx["column_name"])

            indexes = list(indexes_dict.values())

            tables.append({
                "name": table_name,
                "columns": columns,
                "indexes": indexes,
            })

        return {
            "schemas": [{
                "name": self.config.database or "default",
                "tables": tables,
            }]
        }

    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create MySQL backup using mysqldump"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # Build mysqldump command
        cmd = [
            "mysqldump",
            f"--host={self.config.host or 'localhost'}",
            f"--port={self.config.port or 3306}",
            f"--user={self.config.username}",
            f"--password={self.config.password}",
            self.config.database,
        ]

        # Run mysqldump
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"mysqldump failed: {stderr.decode()}")

        # Write output to file
        backup_file.write_bytes(stdout)
        return str(backup_file)

    async def restore_backup(self, backup_path: str) -> None:
        """Restore MySQL backup"""
        if not self.connection:
            await self.connect()

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Read backup file
        backup_data = backup_file.read_bytes()

        # Build mysql command
        cmd = [
            "mysql",
            f"--host={self.config.host or 'localhost'}",
            f"--port={self.config.port or 3306}",
            f"--user={self.config.username}",
            f"--password={self.config.password}",
            self.config.database,
        ]

        # Run mysql restore
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate(input=backup_data)

        if process.returncode != 0:
            raise RuntimeError(f"mysql restore failed: {stderr.decode()}")

