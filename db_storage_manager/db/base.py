"""
Base database connection interface
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypedDict
from dataclasses import dataclass


@dataclass
class ConnectionConfig:
    """Database connection configuration"""
    id: str
    name: str
    type: str  # postgresql, mysql, sqlite, mongodb, redis, oracle, sqlserver, clickhouse, influxdb
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connection_string: Optional[str] = None
    ssh_config: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class TableInfo(TypedDict):
    """Table information"""
    name: str
    size: int
    rowCount: int
    indexSize: int
    bloat: float


class IndexInfo(TypedDict):
    """Index information"""
    name: str
    tableName: str
    size: int
    bloat: float


class StorageAnalysis(TypedDict):
    """Storage analysis results"""
    totalSize: int
    tableCount: int
    indexCount: int
    largestTable: TableInfo
    tables: List[TableInfo]
    indexes: List[IndexInfo]
    lastAnalyzed: str


class QueryResult(TypedDict):
    """Query execution result"""
    columns: List[str]
    rows: List[Dict[str, Any]]
    rowCount: int
    executionTime: int
    explainPlan: Optional[Any]


class ColumnInfo(TypedDict):
    """Column information"""
    name: str
    type: str
    nullable: bool
    defaultValue: Optional[Any]


class TableSchema(TypedDict):
    """Table schema information"""
    name: str
    columns: List[ColumnInfo]
    indexes: List[Dict[str, Any]]


class SchemaInfo(TypedDict, total=False):
    """Database schema information"""
    tables: List[str]
    views: List[str]
    procedures: List[str]
    schemas: List[Dict[str, Any]]  # For databases with schema support (PostgreSQL)


class DatabaseConnection(ABC):
    """Base class for database connections"""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.connected = False

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the database"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the database"""
        pass

    @abstractmethod
    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze database storage"""
        pass

    @abstractmethod
    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute a query"""
        pass

    @abstractmethod
    async def get_schema(self) -> SchemaInfo:
        """Get database schema"""
        pass

    @abstractmethod
    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create a backup of the database"""
        pass

    @abstractmethod
    async def restore_backup(self, backup_path: str) -> None:
        """Restore a backup to the database"""
        pass

    async def test_connection(self) -> bool:
        """Test database connection"""
        try:
            await self.connect()
            await self.disconnect()
            return True
        except Exception:
            return False

