"""
ClickHouse database connection
"""

import asyncio
from typing import Any, Dict, List

try:
    from clickhouse_driver import Client
except ImportError:
    Client = None

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class ClickHouseConnection(DatabaseConnection):
    """ClickHouse database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.client = None
        if Client is None:
            raise ImportError(
                "clickhouse-driver is required for ClickHouse support. Install it with: pip install clickhouse-driver"
            )

    async def connect(self) -> None:
        """Connect to ClickHouse database"""
        self.client = Client(
            host=self.config.host or "localhost",
            port=self.config.port or 9000,
            database=self.config.database or "default",
            user=self.config.username or "default",
            password=self.config.password or "",
        )
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from ClickHouse database"""
        if self.client:
            self.client.disconnect()
            self.client = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze ClickHouse storage"""
        if not self.client:
            await self.connect()

        # Get table sizes
        result = self.client.execute(
            """
            SELECT 
                database || '.' || table AS name,
                formatReadableSize(sum(bytes)) as size_str,
                sum(bytes) as size,
                sum(rows) as row_count
            FROM system.parts
            WHERE active = 1
            GROUP BY database, table
            ORDER BY sum(bytes) DESC
        """
        )

        tables = []
        total_size = 0
        for row in result:
            table_size = row[2] or 0
            tables.append(
                {
                    "name": row[0],
                    "size": table_size,
                    "rowCount": row[3] or 0,
                    "indexSize": 0,
                    "bloat": 0.0,
                }
            )
            total_size += table_size

        largest_table = (
            max(tables, key=lambda t: t["size"])
            if tables
            else {"name": "", "size": 0, "rowCount": 0, "indexSize": 0, "bloat": 0.0}
        )

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": 0,
            "largestTable": largest_table,
            "tables": tables,
            "indexes": [],
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute query on ClickHouse database"""
        if not self.client:
            await self.connect()

        if safe_mode and not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed in safe mode")

        result = self.client.execute(query, with_column_types=True)

        if result:
            columns = [col[0] for col in result[1]]
            rows = []
            for row in result[0]:
                rows.append(dict(zip(columns, row)))
            return {
                "columns": columns,
                "rows": rows,
                "rowCount": len(rows),
            }
        else:
            return {
                "columns": [],
                "rows": [],
                "rowCount": 0,
            }

    async def get_schema(self) -> SchemaInfo:
        """Get ClickHouse database schema"""
        if not self.client:
            await self.connect()

        # Get tables
        result = self.client.execute(
            """
            SELECT name
            FROM system.tables
            WHERE database = currentDatabase()
            ORDER BY name
        """
        )
        tables = [row[0] for row in result]

        return {
            "tables": tables,
            "views": [],
            "procedures": [],
        }

    async def test_connection(self) -> bool:
        """Test ClickHouse connection"""
        try:
            await self.connect()
            self.client.execute("SELECT 1")
            await self.disconnect()
            return True
        except Exception:
            return False

    async def create_backup(self, backup_path: str) -> str:
        """Create ClickHouse backup"""
        import subprocess

        if not self.client:
            await self.connect()

        # Use clickhouse-backup or clickhouse-client for backup
        backup_file = f"{backup_path}.sql"

        # Export schema and data
        tables = await self.get_schema()
        with open(backup_file, "w") as f:
            for table in tables["tables"]:
                result = self.client.execute(f"SHOW CREATE TABLE {table}")
                f.write(f"{result[0][0]};\n")
                # Export data
                data = self.client.execute(f"SELECT * FROM {table}")
                for row in data:
                    f.write(f"INSERT INTO {table} VALUES {row};\n")

        return backup_file

    async def restore_backup(self, backup_path: str) -> None:
        """Restore ClickHouse backup"""
        if not self.client:
            await self.connect()

        # Read and execute backup file
        with open(backup_path, "r") as f:
            query = ""
            for line in f:
                query += line
                if line.strip().endswith(";"):
                    self.client.execute(query)
                    query = ""
