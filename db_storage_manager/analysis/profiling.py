"""
Performance profiling and bottleneck identification
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import time
from ..db.base import DatabaseConnection


class PerformanceProfiler:
    """Performance profiler for database operations"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.profiles: List[Dict[str, Any]] = []

    async def profile_query(self, query: str) -> Dict[str, Any]:
        """Profile a query execution"""
        start_time = time.time()

        # Execute query
        result = await self.connection.execute_query(query, safe_mode=True)

        execution_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        # Get explain plan if available
        explain_plan = None
        try:
            db_type = self.connection.config.type.lower()
            if db_type in ["postgresql", "postgres"]:
                explain_query = f"EXPLAIN ANALYZE {query}"
                explain_result = await self.connection.execute_query(
                    explain_query, safe_mode=True
                )
                explain_plan = explain_result.get("rows", [])
        except Exception:
            pass

        profile = {
            "query": query,
            "execution_time": execution_time,
            "row_count": result.get("rowCount", 0),
            "explain_plan": explain_plan,
            "timestamp": datetime.now().isoformat(),
        }

        self.profiles.append(profile)
        return profile

    def identify_bottlenecks(self) -> List[Dict[str, Any]]:
        """Identify performance bottlenecks"""
        bottlenecks = []

        # Find slow queries
        slow_queries = [p for p in self.profiles if p.get("execution_time", 0) > 1000]
        if slow_queries:
            bottlenecks.append(
                {
                    "type": "slow_queries",
                    "severity": "high",
                    "count": len(slow_queries),
                    "queries": slow_queries[:10],  # Top 10
                }
            )

        # Analyze explain plans for issues
        for profile in self.profiles:
            explain_plan = profile.get("explain_plan")
            if explain_plan:
                # Check for sequential scans, missing indexes, etc.
                plan_text = str(explain_plan).lower()
                if "seq scan" in plan_text or "sequential scan" in plan_text:
                    bottlenecks.append(
                        {
                            "type": "sequential_scan",
                            "severity": "medium",
                            "query": profile.get("query", "")[:100],
                        }
                    )

        return bottlenecks

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        if not self.profiles:
            return {
                "total_queries": 0,
                "average_time": 0,
                "slow_queries": 0,
            }

        execution_times = [p.get("execution_time", 0) for p in self.profiles]

        return {
            "total_queries": len(self.profiles),
            "average_time": sum(execution_times) / len(execution_times),
            "min_time": min(execution_times),
            "max_time": max(execution_times),
            "slow_queries": len([t for t in execution_times if t > 1000]),
        }
