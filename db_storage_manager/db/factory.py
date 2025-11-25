"""
Database connection factory
"""

from typing import Optional
from .base import DatabaseConnection, ConnectionConfig
from .postgres import PostgreSQLConnection
from .mysql import MySQLConnection
from .sqlite import SQLiteConnection
from .mongo import MongoDBConnection
from .redis import RedisConnection
from .oracle import OracleConnection
from .sqlserver import SQLServerConnection
from .clickhouse import ClickHouseConnection
from .influxdb import InfluxDBConnection


class DatabaseConnectionFactory:
    """Factory for creating database connections"""

    @staticmethod
    def create_connection(config: ConnectionConfig) -> DatabaseConnection:
        """Create a database connection based on type"""
        db_type = config.type.lower()

        if db_type == "postgresql" or db_type == "postgres":
            return PostgreSQLConnection(config)
        elif db_type == "mysql" or db_type == "mariadb":
            return MySQLConnection(config)
        elif db_type == "sqlite":
            return SQLiteConnection(config)
        elif db_type == "mongodb" or db_type == "mongo":
            return MongoDBConnection(config)
        elif db_type == "redis":
            return RedisConnection(config)
        elif db_type == "oracle":
            return OracleConnection(config)
        elif db_type == "sqlserver" or db_type == "mssql" or db_type == "sql-server":
            return SQLServerConnection(config)
        elif db_type == "clickhouse":
            return ClickHouseConnection(config)
        elif db_type == "influxdb" or db_type == "influx":
            return InfluxDBConnection(config)
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

