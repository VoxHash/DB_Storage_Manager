"""
Database metrics collection
"""

import asyncio
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from ..db.base import DatabaseConnection


class MetricsCollector:
    """Collect real-time database metrics"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.metrics_history: List[Dict[str, Any]] = []
        self.collecting = False

    async def collect_metrics(self) -> Dict[str, Any]:
        """Collect current database metrics"""
        db_type = self.connection.config.type.lower()

        if db_type in ["postgresql", "postgres"]:
            return await self._collect_postgres_metrics()
        elif db_type in ["mysql", "mariadb"]:
            return await self._collect_mysql_metrics()
        elif db_type == "sqlserver" or db_type == "mssql":
            return await self._collect_sqlserver_metrics()
        else:
            return await self._collect_basic_metrics()

    async def _collect_postgres_metrics(self) -> Dict[str, Any]:
        """Collect PostgreSQL-specific metrics"""
        if not self.connection.connected:
            await self.connection.connect()

        try:
            result = await self.connection.execute_query(
                """
                SELECT 
                    (SELECT count(*) FROM pg_stat_activity) as active_connections,
                    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') as active_queries,
                    (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle') as idle_connections,
                    (SELECT sum(xact_commit) FROM pg_stat_database WHERE datname = current_database()) as transactions_committed,
                    (SELECT sum(xact_rollback) FROM pg_stat_database WHERE datname = current_database()) as transactions_rolled_back,
                    (SELECT sum(blks_read) FROM pg_stat_database WHERE datname = current_database()) as blocks_read,
                    (SELECT sum(blks_hit) FROM pg_stat_database WHERE datname = current_database()) as blocks_hit,
                    (SELECT pg_database_size(current_database())) as database_size
            """,
                safe_mode=True,
            )

            if result.get("rows"):
                row = result["rows"][0]
                return {
                    "timestamp": datetime.now().isoformat(),
                    "activeConnections": row.get("active_connections", 0),
                    "activeQueries": row.get("active_queries", 0),
                    "idleConnections": row.get("idle_connections", 0),
                    "transactionsCommitted": row.get("transactions_committed", 0),
                    "transactionsRolledBack": row.get("transactions_rolled_back", 0),
                    "blocksRead": row.get("blocks_read", 0),
                    "blocksHit": row.get("blocks_hit", 0),
                    "databaseSize": row.get("database_size", 0),
                    "cacheHitRatio": (
                        row.get("blocks_hit", 0)
                        / (row.get("blocks_read", 0) + row.get("blocks_hit", 1))
                        * 100
                        if (row.get("blocks_read", 0) + row.get("blocks_hit", 0)) > 0
                        else 0
                    ),
                }
        except Exception:
            pass

        return await self._collect_basic_metrics()

    async def _collect_mysql_metrics(self) -> Dict[str, Any]:
        """Collect MySQL-specific metrics"""
        if not self.connection.connected:
            await self.connection.connect()

        try:
            result = await self.connection.execute_query(
                """
                SHOW STATUS WHERE Variable_name IN (
                    'Threads_connected',
                    'Threads_running',
                    'Questions',
                    'Com_commit',
                    'Com_rollback',
                    'Innodb_buffer_pool_read_requests',
                    'Innodb_buffer_pool_reads'
                )
            """,
                safe_mode=True,
            )

            metrics = {}
            for row in result.get("rows", []):
                metrics[row.get("Variable_name", "").lower()] = int(row.get("Value", 0))

            return {
                "timestamp": datetime.now().isoformat(),
                "activeConnections": metrics.get("threads_connected", 0),
                "activeQueries": metrics.get("threads_running", 0),
                "totalQueries": metrics.get("questions", 0),
                "transactionsCommitted": metrics.get("com_commit", 0),
                "transactionsRolledBack": metrics.get("com_rollback", 0),
                "cacheHitRatio": (
                    metrics.get("innodb_buffer_pool_read_requests", 0)
                    / (
                        metrics.get("innodb_buffer_pool_reads", 0)
                        + metrics.get("innodb_buffer_pool_read_requests", 1)
                    )
                    * 100
                    if (
                        metrics.get("innodb_buffer_pool_reads", 0)
                        + metrics.get("innodb_buffer_pool_read_requests", 0)
                    )
                    > 0
                    else 0
                ),
            }
        except Exception:
            pass

        return await self._collect_basic_metrics()

    async def _collect_sqlserver_metrics(self) -> Dict[str, Any]:
        """Collect SQL Server-specific metrics"""
        if not self.connection.connected:
            await self.connection.connect()

        try:
            result = await self.connection.execute_query(
                """
                SELECT 
                    (SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE is_user_process = 1) as active_connections,
                    (SELECT COUNT(*) FROM sys.dm_exec_requests WHERE status = 'running') as active_queries,
                    (SELECT cntr_value FROM sys.dm_os_performance_counters WHERE counter_name = 'Transactions/sec') as transactions_per_sec
            """,
                safe_mode=True,
            )

            if result.get("rows"):
                row = result["rows"][0]
                return {
                    "timestamp": datetime.now().isoformat(),
                    "activeConnections": row.get("active_connections", 0),
                    "activeQueries": row.get("active_queries", 0),
                    "transactionsPerSecond": row.get("transactions_per_sec", 0),
                }
        except Exception:
            pass

        return await self._collect_basic_metrics()

    async def _collect_basic_metrics(self) -> Dict[str, Any]:
        """Collect basic metrics for any database"""
        return {
            "timestamp": datetime.now().isoformat(),
            "connected": self.connection.connected,
            "databaseType": self.connection.config.type,
        }

    async def start_collecting(
        self, interval_seconds: int = 60, callback: Optional[Callable] = None
    ) -> None:
        """Start collecting metrics at regular intervals"""
        self.collecting = True

        while self.collecting:
            try:
                metrics = await self.collect_metrics()
                self.metrics_history.append(metrics)

                # Keep only last 1000 entries
                if len(self.metrics_history) > 1000:
                    self.metrics_history = self.metrics_history[-1000:]

                if callback:
                    callback(metrics)

                await asyncio.sleep(interval_seconds)
            except Exception as e:
                print(f"Error collecting metrics: {e}")
                await asyncio.sleep(interval_seconds)

    def stop_collecting(self) -> None:
        """Stop collecting metrics"""
        self.collecting = False

    def get_metrics_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get metrics history"""
        return self.metrics_history[-limit:]

    def get_latest_metrics(self) -> Optional[Dict[str, Any]]:
        """Get latest metrics"""
        return self.metrics_history[-1] if self.metrics_history else None
