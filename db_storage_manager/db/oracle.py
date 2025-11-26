"""
Oracle Database connection
"""

import asyncio
from typing import Any, Dict, List

try:
    import cx_Oracle
except ImportError:
    cx_Oracle = None

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class OracleConnection(DatabaseConnection):
    """Oracle Database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None
        if cx_Oracle is None:
            raise ImportError(
                "cx_Oracle is required for Oracle support. Install it with: pip install cx_Oracle"
            )

    async def connect(self) -> None:
        """Connect to Oracle database"""
        if self.config.connection_string:
            self.connection = cx_Oracle.connect(self.config.connection_string)
        else:
            dsn = cx_Oracle.makedsn(
                self.config.host or "localhost",
                self.config.port or 1521,
                service_name=self.config.database or "ORCL",
            )
            self.connection = cx_Oracle.connect(
                user=self.config.username, password=self.config.password, dsn=dsn
            )
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from Oracle database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze Oracle storage"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()

        # Get table sizes
        cursor.execute(
            """
            SELECT 
                owner || '.' || table_name as name,
                num_rows as row_count,
                blocks * (SELECT value FROM v$parameter WHERE name = 'db_block_size') as size
            FROM all_tables
            WHERE owner NOT IN ('SYS', 'SYSTEM', 'SYSAUX')
            ORDER BY blocks DESC
        """
        )

        tables = []
        total_size = 0
        for row in cursor.fetchall():
            table_size = row[2] or 0
            tables.append(
                {
                    "name": row[0],
                    "size": table_size,
                    "rowCount": row[1] or 0,
                    "indexSize": 0,
                    "bloat": 0.0,
                }
            )
            total_size += table_size

        # Get indexes
        cursor.execute(
            """
            SELECT 
                owner || '.' || index_name as name,
                table_name,
                leaf_blocks * (SELECT value FROM v$parameter WHERE name = 'db_block_size') as size
            FROM all_indexes
            WHERE owner NOT IN ('SYS', 'SYSTEM', 'SYSAUX')
        """
        )

        indexes = []
        index_total = 0
        for row in cursor.fetchall():
            index_size = row[2] or 0
            indexes.append(
                {
                    "name": row[0],
                    "tableName": row[1],
                    "size": index_size,
                    "bloat": 0.0,
                }
            )
            index_total += index_size

        cursor.close()

        largest_table = (
            max(tables, key=lambda t: t["size"])
            if tables
            else {"name": "", "size": 0, "rowCount": 0, "indexSize": 0, "bloat": 0.0}
        )

        return {
            "totalSize": total_size + index_total,
            "tableCount": len(tables),
            "indexCount": len(indexes),
            "largestTable": largest_table,
            "tables": tables,
            "indexes": indexes,
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute query on Oracle database"""
        if not self.connection:
            await self.connect()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        cursor = self.connection.cursor()
        try:
            cursor.execute(query)

            if query.strip().upper().startswith("SELECT"):
                columns = [desc[0] for desc in cursor.description]
                rows = []
                for row in cursor.fetchall():
                    rows.append(dict(zip(columns, row)))
                return {
                    "columns": columns,
                    "rows": rows,
                    "rowCount": len(rows),
                }
            else:
                self.connection.commit()
                return {
                    "columns": [],
                    "rows": [],
                    "rowCount": cursor.rowcount,
                }
        finally:
            cursor.close()

    async def get_schema(self) -> SchemaInfo:
        """Get Oracle database schema"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()

        # Get tables
        cursor.execute(
            """
            SELECT table_name
            FROM all_tables
            WHERE owner = USER
            ORDER BY table_name
        """
        )
        tables = [row[0] for row in cursor.fetchall()]

        # Get views
        cursor.execute(
            """
            SELECT view_name
            FROM all_views
            WHERE owner = USER
            ORDER BY view_name
        """
        )
        views = [row[0] for row in cursor.fetchall()]

        cursor.close()

        return {
            "tables": tables,
            "views": views,
            "procedures": [],
        }

    async def test_connection(self) -> bool:
        """Test Oracle connection"""
        try:
            await self.connect()
            await self.disconnect()
            return True
        except Exception:
            return False

    async def create_backup(self, backup_path: str) -> str:
        """Create Oracle backup using expdp"""
        import subprocess
        import os

        if not self.connection:
            await self.connect()

        # Use expdp for Oracle backup
        backup_file = f"{backup_path}.dmp"
        log_file = f"{backup_path}.log"

        # Build expdp command
        cmd = [
            "expdp",
            f"{self.config.username}/{self.config.password}@{self.config.host}:{self.config.port or 1521}/{self.config.database}",
            f"DIRECTORY=DATA_PUMP_DIR",
            f"DUMPFILE={os.path.basename(backup_file)}",
            f"LOGFILE={os.path.basename(log_file)}",
            "SCHEMAS=" + self.config.username,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Oracle backup failed: {result.stderr}")

        return backup_file

    async def restore_backup(self, backup_path: str) -> None:
        """Restore Oracle backup using impdp"""
        import subprocess

        if not self.connection:
            await self.connect()

        # Use impdp for Oracle restore
        cmd = [
            "impdp",
            f"{self.config.username}/{self.config.password}@{self.config.host}:{self.config.port or 1521}/{self.config.database}",
            f"DIRECTORY=DATA_PUMP_DIR",
            f"DUMPFILE={os.path.basename(backup_path)}",
            "SCHEMAS=" + self.config.username,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Oracle restore failed: {result.stderr}")
