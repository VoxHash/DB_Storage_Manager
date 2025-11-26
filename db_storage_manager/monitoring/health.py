"""
Database health monitoring
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum
from ..db.base import DatabaseConnection


class HealthStatus(Enum):
    """Health status levels"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthChecker:
    """Check database health"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.health_history: List[Dict[str, Any]] = []

    async def check_health(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        checks = {
            "connectivity": await self._check_connectivity(),
            "response_time": await self._check_response_time(),
            "query_performance": await self._check_query_performance(),
            "connection_pool": await self._check_connection_pool(),
        }

        # Determine overall health
        overall_status = self._determine_overall_health(checks)

        health_report = {
            "timestamp": datetime.now().isoformat(),
            "status": overall_status.value,
            "checks": checks,
            "databaseType": self.connection.config.type,
        }

        self.health_history.append(health_report)

        # Keep only last 100 entries
        if len(self.health_history) > 100:
            self.health_history = self.health_history[-100:]

        return health_report

    async def _check_connectivity(self) -> Dict[str, Any]:
        """Check database connectivity"""
        try:
            is_connected = await self.connection.test_connection()
            return {
                "status": "healthy" if is_connected else "unhealthy",
                "connected": is_connected,
                "message": (
                    "Connection successful" if is_connected else "Connection failed"
                ),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "message": f"Connection error: {str(e)}",
            }

    async def _check_response_time(self) -> Dict[str, Any]:
        """Check database response time"""
        import time

        try:
            start_time = time.time()
            await self.connection.test_connection()
            response_time = (time.time() - start_time) * 1000  # Convert to milliseconds

            if response_time < 100:
                status = "healthy"
            elif response_time < 500:
                status = "degraded"
            else:
                status = "unhealthy"

            return {
                "status": status,
                "responseTime": response_time,
                "message": f"Response time: {response_time:.2f}ms",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "responseTime": None,
                "message": f"Response time check failed: {str(e)}",
            }

    async def _check_query_performance(self) -> Dict[str, Any]:
        """Check query performance"""
        db_type = self.connection.config.type.lower()

        # Simple test query based on database type
        test_queries = {
            "postgresql": "SELECT 1",
            "postgres": "SELECT 1",
            "mysql": "SELECT 1",
            "mariadb": "SELECT 1",
            "sqlite": "SELECT 1",
            "sqlserver": "SELECT 1",
            "mssql": "SELECT 1",
            "oracle": "SELECT 1 FROM DUAL",
        }

        test_query = test_queries.get(db_type, "SELECT 1")

        try:
            import time

            start_time = time.time()
            result = await self.connection.execute_query(test_query, safe_mode=True)
            execution_time = (time.time() - start_time) * 1000

            if execution_time < 50:
                status = "healthy"
            elif execution_time < 200:
                status = "degraded"
            else:
                status = "unhealthy"

            return {
                "status": status,
                "executionTime": execution_time,
                "message": f"Test query executed in {execution_time:.2f}ms",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "executionTime": None,
                "message": f"Query performance check failed: {str(e)}",
            }

    async def _check_connection_pool(self) -> Dict[str, Any]:
        """Check connection pool status"""
        # This is a placeholder - actual implementation depends on database type
        return {
            "status": "healthy",
            "message": "Connection pool check not implemented for this database type",
        }

    def _determine_overall_health(
        self, checks: Dict[str, Dict[str, Any]]
    ) -> HealthStatus:
        """Determine overall health status from individual checks"""
        statuses = [check.get("status") for check in checks.values()]

        if "unhealthy" in statuses:
            return HealthStatus.UNHEALTHY
        elif "degraded" in statuses:
            return HealthStatus.DEGRADED
        elif all(s == "healthy" for s in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN

    def get_health_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get health check history"""
        return self.health_history[-limit:]

    def get_current_health(self) -> Optional[Dict[str, Any]]:
        """Get most recent health check"""
        return self.health_history[-1] if self.health_history else None
