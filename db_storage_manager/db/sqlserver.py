"""
Microsoft SQL Server database connection
"""

import asyncio
from typing import Any, Dict, List
try:
    import pyodbc
except ImportError:
    pyodbc = None

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class SQLServerConnection(DatabaseConnection):
    """Microsoft SQL Server database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None
        if pyodbc is None:
            raise ImportError("pyodbc is required for SQL Server support. Install it with: pip install pyodbc")

    async def connect(self) -> None:
        """Connect to SQL Server database"""
        if self.config.connection_string:
            self.connection = pyodbc.connect(self.config.connection_string)
        else:
            driver = "{ODBC Driver 17 for SQL Server}"  # Try common driver
            conn_str = (
                f"DRIVER={driver};"
                f"SERVER={self.config.host or 'localhost'},{self.config.port or 1433};"
                f"DATABASE={self.config.database};"
                f"UID={self.config.username};"
                f"PWD={self.config.password}"
            )
            self.connection = pyodbc.connect(conn_str)
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from SQL Server database"""
        if self.connection:
            self.connection.close()
            self.connection = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze SQL Server storage"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()

        # Get table sizes
        cursor.execute("""
            SELECT 
                t.NAME AS name,
                p.rows AS row_count,
                SUM(a.total_pages) * 8 * 1024 AS size
            FROM sys.tables t
            INNER JOIN sys.indexes i ON t.OBJECT_ID = i.object_id
            INNER JOIN sys.partitions p ON i.object_id = p.OBJECT_ID AND i.index_id = p.index_id
            INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
            WHERE t.NAME NOT LIKE 'dt%' AND t.is_ms_shipped = 0 AND i.OBJECT_ID > 255
            GROUP BY t.NAME, p.rows
            ORDER BY size DESC
        """)

        tables = []
        total_size = 0
        for row in cursor.fetchall():
            table_size = row[2] or 0
            tables.append({
                "name": row[0],
                "size": table_size,
                "rowCount": row[1] or 0,
                "indexSize": 0,
                "bloat": 0.0,
            })
            total_size += table_size

        # Get indexes
        cursor.execute("""
            SELECT 
                i.name AS name,
                OBJECT_NAME(i.object_id) AS table_name,
                SUM(s.used_page_count) * 8 * 1024 AS size
            FROM sys.indexes i
            INNER JOIN sys.dm_db_partition_stats s ON i.object_id = s.object_id AND i.index_id = s.index_id
            WHERE i.object_id > 255
            GROUP BY i.name, i.object_id
        """)

        indexes = []
        index_total = 0
        for row in cursor.fetchall():
            index_size = row[2] or 0
            indexes.append({
                "name": row[0],
                "tableName": row[1],
                "size": index_size,
                "bloat": 0.0,
            })
            index_total += index_size

        cursor.close()

        largest_table = max(tables, key=lambda t: t["size"]) if tables else {
            "name": "", "size": 0, "rowCount": 0, "indexSize": 0, "bloat": 0.0
        }

        return {
            "totalSize": total_size + index_total,
            "tableCount": len(tables),
            "indexCount": len(indexes),
            "largestTable": largest_table,
            "tables": tables,
            "indexes": indexes,
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute query on SQL Server database"""
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
        """Get SQL Server database schema"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()

        # Get tables
        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = [row[0] for row in cursor.fetchall()]

        # Get views
        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.VIEWS
            ORDER BY TABLE_NAME
        """)
        views = [row[0] for row in cursor.fetchall()]

        # Get stored procedures
        cursor.execute("""
            SELECT ROUTINE_NAME
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_TYPE = 'PROCEDURE'
            ORDER BY ROUTINE_NAME
        """)
        procedures = [row[0] for row in cursor.fetchall()]

        cursor.close()

        return {
            "tables": tables,
            "views": views,
            "procedures": procedures,
        }

    async def test_connection(self) -> bool:
        """Test SQL Server connection"""
        try:
            await self.connect()
            await self.disconnect()
            return True
        except Exception:
            return False

    async def create_backup(self, backup_path: str) -> str:
        """Create SQL Server backup"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()
        backup_file = f"{backup_path}.bak"
        
        try:
            cursor.execute(f"""
                BACKUP DATABASE [{self.config.database}]
                TO DISK = '{backup_file}'
                WITH FORMAT, INIT, NAME = 'Full Backup of {self.config.database}'
            """)
            self.connection.commit()
            return backup_file
        finally:
            cursor.close()

    async def restore_backup(self, backup_path: str) -> None:
        """Restore SQL Server backup"""
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()
        try:
            cursor.execute(f"""
                RESTORE DATABASE [{self.config.database}]
                FROM DISK = '{backup_path}'
                WITH REPLACE
            """)
            self.connection.commit()
        finally:
            cursor.close()

