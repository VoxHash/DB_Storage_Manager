"""
Oracle Database connection

Uses python-oracledb (`oracledb`) in Thin mode by default (no Instant Client).
Falls back to legacy `cx_Oracle` if that package is installed instead.
"""

import asyncio
import os
from typing import Any, Dict, List

try:
    import oracledb as _oracle_driver
except ImportError:
    try:
        import cx_Oracle as _oracle_driver  # type: ignore[no-redef]
    except ImportError:
        _oracle_driver = None

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)
from .optional_deps import missing_driver_error

_oracle_client_initialized = False


def _ensure_thick_mode_if_requested() -> None:
    """Optionally enable Thick mode when ORACLE_CLIENT_LIB_DIR is set."""
    global _oracle_client_initialized
    if _oracle_driver is None or _oracle_client_initialized:
        return
    lib_dir = os.environ.get("ORACLE_CLIENT_LIB_DIR")
    if not lib_dir:
        return
    init = getattr(_oracle_driver, "init_oracle_client", None)
    if init is None:
        return
    init(lib_dir=lib_dir)
    _oracle_client_initialized = True


class OracleConnection(DatabaseConnection):
    """Oracle Database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.connection = None
        if _oracle_driver is None:
            raise missing_driver_error("oracle")

    async def connect(self) -> None:
        """Connect to Oracle database"""
        _ensure_thick_mode_if_requested()
        if self.config.connection_string:
            self.connection = _oracle_driver.connect(self.config.connection_string)
        else:
            dsn = _oracle_driver.makedsn(
                self.config.host or "localhost",
                self.config.port or 1521,
                service_name=self.config.database or "ORCL",
            )
            self.connection = _oracle_driver.connect(
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
