"""
Database connection modules
"""

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)
from .factory import DatabaseConnectionFactory
from .pool import (
    PoolClosedError,
    PoolExhaustedError,
    SQLEnginePool,
    get_sql_engine_pool,
    is_sql_engine,
    shutdown_sql_engine_pool,
)

__all__ = [
    "DatabaseConnection",
    "ConnectionConfig",
    "StorageAnalysis",
    "QueryResult",
    "SchemaInfo",
    "DatabaseConnectionFactory",
    "SQLEnginePool",
    "PoolClosedError",
    "PoolExhaustedError",
    "get_sql_engine_pool",
    "is_sql_engine",
    "shutdown_sql_engine_pool",
]
