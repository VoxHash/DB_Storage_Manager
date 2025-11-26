"""
Index optimization suggestions
"""

from typing import Dict, List, Any
from ..db.base import DatabaseConnection, StorageAnalysis


class IndexOptimizer:
    """Provide index optimization suggestions"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection

    async def analyze_indexes(self, analysis: StorageAnalysis) -> List[Dict[str, Any]]:
        """Analyze indexes and provide optimization suggestions"""
        suggestions = []
        db_type = self.connection.config.type.lower()

        if db_type in ["postgresql", "postgres"]:
            suggestions = await self._analyze_postgres_indexes(analysis)
        elif db_type in ["mysql", "mariadb"]:
            suggestions = await self._analyze_mysql_indexes(analysis)
        elif db_type == "sqlserver" or db_type == "mssql":
            suggestions = await self._analyze_sqlserver_indexes(analysis)

        return suggestions

    async def _analyze_postgres_indexes(
        self, analysis: StorageAnalysis
    ) -> List[Dict[str, Any]]:
        """Analyze PostgreSQL indexes"""
        suggestions = []

        # Check for tables without indexes
        for table in analysis.get("tables", []):
            table_indexes = [
                idx
                for idx in analysis.get("indexes", [])
                if idx.get("tableName") == table.get("name")
            ]

            if not table_indexes and table.get("rowCount", 0) > 1000:
                suggestions.append(
                    {
                        "type": "missing_index",
                        "severity": "medium",
                        "table": table.get("name"),
                        "message": f"Table {table.get('name')} has {table.get('rowCount')} rows but no indexes",
                        "recommendation": f"Consider adding indexes on frequently queried columns in {table.get('name')}",
                    }
                )

            # Check for high bloat indexes
            for idx in table_indexes:
                if idx.get("bloat", 0) > 30.0:
                    suggestions.append(
                        {
                            "type": "index_bloat",
                            "severity": "high",
                            "index": idx.get("name"),
                            "table": idx.get("tableName"),
                            "bloat": idx.get("bloat"),
                            "message": f"Index {idx.get('name')} has {idx.get('bloat'):.2f}% bloat",
                            "recommendation": f"Consider rebuilding index {idx.get('name')} to reduce bloat",
                        }
                    )

        return suggestions

    async def _analyze_mysql_indexes(
        self, analysis: StorageAnalysis
    ) -> List[Dict[str, Any]]:
        """Analyze MySQL indexes"""
        suggestions = []

        # Check for large tables without indexes
        for table in analysis.get("tables", []):
            table_indexes = [
                idx
                for idx in analysis.get("indexes", [])
                if idx.get("tableName") == table.get("name")
            ]

            if not table_indexes and table.get("rowCount", 0) > 1000:
                suggestions.append(
                    {
                        "type": "missing_index",
                        "severity": "medium",
                        "table": table.get("name"),
                        "message": f"Table {table.get('name')} has {table.get('rowCount')} rows but no indexes",
                        "recommendation": f"Add indexes on foreign keys and frequently queried columns",
                    }
                )

        return suggestions

    async def _analyze_sqlserver_indexes(
        self, analysis: StorageAnalysis
    ) -> List[Dict[str, Any]]:
        """Analyze SQL Server indexes"""
        suggestions = []

        # Check for missing indexes (SQL Server specific)
        if self.connection.connected:
            try:
                result = await self.connection.execute_query(
                    """
                    SELECT 
                        OBJECT_NAME(d.object_id) AS table_name,
                        d.equality_columns,
                        d.inequality_columns,
                        d.included_columns,
                        s.avg_user_impact
                    FROM sys.dm_db_missing_index_details d
                    INNER JOIN sys.dm_db_missing_index_groups g ON d.index_handle = g.index_handle
                    INNER JOIN sys.dm_db_missing_index_group_stats s ON g.index_group_handle = s.group_handle
                    WHERE s.avg_user_impact > 50
                    ORDER BY s.avg_user_impact DESC
                """,
                    safe_mode=True,
                )

                for row in result.get("rows", []):
                    suggestions.append(
                        {
                            "type": "missing_index",
                            "severity": "high",
                            "table": row.get("table_name"),
                            "message": f"Missing index on {row.get('table_name')} could improve performance by {row.get('avg_user_impact')}%",
                            "recommendation": f"Create index on {row.get('equality_columns')} for table {row.get('table_name')}",
                        }
                    )
            except Exception:
                pass

        return suggestions

    async def get_optimization_recommendations(
        self, analysis: StorageAnalysis
    ) -> Dict[str, Any]:
        """Get comprehensive optimization recommendations"""
        suggestions = await self.analyze_indexes(analysis)

        high_priority = [s for s in suggestions if s.get("severity") == "high"]
        medium_priority = [s for s in suggestions if s.get("severity") == "medium"]
        low_priority = [s for s in suggestions if s.get("severity") == "low"]

        return {
            "totalSuggestions": len(suggestions),
            "highPriority": high_priority,
            "mediumPriority": medium_priority,
            "lowPriority": low_priority,
            "suggestions": suggestions,
        }
