"""
Query performance analysis
"""

import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from ..db.base import DatabaseConnection, QueryResult


class QueryPerformanceAnalyzer:
    """Analyze query performance"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.query_history: List[Dict[str, Any]] = []

    async def analyze_query(self, query: str) -> Dict[str, Any]:
        """Analyze a query's performance"""
        start_time = time.time()

        try:
            result = await self.connection.execute_query(query, safe_mode=True)
            execution_time = (
                time.time() - start_time
            ) * 1000  # Convert to milliseconds

            analysis = {
                "query": query,
                "executionTime": execution_time,
                "rowCount": result.get("rowCount", 0),
                "columns": result.get("columns", []),
                "timestamp": datetime.now().isoformat(),
                "status": "success",
            }

            # Get explain plan if available
            try:
                explain_plan = await self._get_explain_plan(query)
                analysis["explainPlan"] = explain_plan
            except Exception:
                analysis["explainPlan"] = None

            self.query_history.append(analysis)
            return analysis

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            analysis = {
                "query": query,
                "executionTime": execution_time,
                "rowCount": 0,
                "columns": [],
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e),
            }
            self.query_history.append(analysis)
            return analysis

    async def _get_explain_plan(self, query: str) -> Optional[Dict[str, Any]]:
        """Get query explain plan"""
        db_type = self.connection.config.type.lower()

        if db_type in ["postgresql", "postgres"]:
            explain_query = f"EXPLAIN ANALYZE {query}"
        elif db_type in ["mysql", "mariadb"]:
            explain_query = f"EXPLAIN {query}"
        elif db_type == "sqlite":
            explain_query = f"EXPLAIN QUERY PLAN {query}"
        else:
            return None

        try:
            result = await self.connection.execute_query(explain_query, safe_mode=True)
            return {
                "plan": result.get("rows", []),
                "columns": result.get("columns", []),
            }
        except Exception:
            return None

    def get_slow_queries(self, threshold_ms: float = 1000.0) -> List[Dict[str, Any]]:
        """Get queries that took longer than threshold"""
        return [
            q
            for q in self.query_history
            if q.get("executionTime", 0) > threshold_ms and q.get("status") == "success"
        ]

    def get_query_statistics(self) -> Dict[str, Any]:
        """Get query performance statistics"""
        if not self.query_history:
            return {
                "totalQueries": 0,
                "averageExecutionTime": 0,
                "slowQueries": 0,
                "errorQueries": 0,
            }

        successful_queries = [
            q for q in self.query_history if q.get("status") == "success"
        ]

        if successful_queries:
            avg_time = sum(q.get("executionTime", 0) for q in successful_queries) / len(
                successful_queries
            )
            slow_queries = len(self.get_slow_queries())
        else:
            avg_time = 0
            slow_queries = 0

        return {
            "totalQueries": len(self.query_history),
            "averageExecutionTime": avg_time,
            "slowQueries": slow_queries,
            "errorQueries": len(
                [q for q in self.query_history if q.get("status") == "error"]
            ),
            "successfulQueries": len(successful_queries),
        }
