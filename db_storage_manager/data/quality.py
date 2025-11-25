"""
Data quality analysis
"""

from typing import Dict, Any, List
from ..db.base import DatabaseConnection


class DataQualityAnalyzer:
    """Data quality analyzer"""

    def __init__(self, database: DatabaseConnection):
        self.database = database

    async def analyze_table_quality(self, table_name: str) -> Dict[str, Any]:
        """Analyze data quality for a table"""
        # Check for nulls
        null_check_query = f"""
            SELECT COUNT(*) as total_rows,
                   SUM(CASE WHEN column_name IS NULL THEN 1 ELSE 0 END) as null_count
            FROM {table_name}
        """
        
        # Check for duplicates
        duplicate_check_query = f"""
            SELECT COUNT(*) - COUNT(DISTINCT *) as duplicate_count
            FROM {table_name}
        """
        
        # Get basic stats
        try:
            null_result = await self.database.execute_query(null_check_query, safe_mode=True)
            duplicate_result = await self.database.execute_query(duplicate_check_query, safe_mode=True)
            
            total_rows = null_result.get("rows", [{}])[0].get("total_rows", 0) if null_result.get("rows") else 0
            null_count = null_result.get("rows", [{}])[0].get("null_count", 0) if null_result.get("rows") else 0
            duplicate_count = duplicate_result.get("rows", [{}])[0].get("duplicate_count", 0) if duplicate_result.get("rows") else 0
            
            quality_score = 100.0
            if total_rows > 0:
                quality_score -= (null_count / total_rows) * 50
                quality_score -= (duplicate_count / total_rows) * 50
            
            return {
                "table": table_name,
                "total_rows": total_rows,
                "null_count": null_count,
                "duplicate_count": duplicate_count,
                "quality_score": max(0, quality_score),
                "issues": self._identify_issues(null_count, duplicate_count, total_rows),
            }
        except Exception as e:
            return {
                "table": table_name,
                "error": str(e),
            }

    def _identify_issues(self, null_count: int, duplicate_count: int, total_rows: int) -> List[str]:
        """Identify data quality issues"""
        issues = []
        
        if total_rows > 0:
            null_percentage = (null_count / total_rows) * 100
            duplicate_percentage = (duplicate_count / total_rows) * 100
            
            if null_percentage > 10:
                issues.append(f"High null percentage: {null_percentage:.2f}%")
            
            if duplicate_percentage > 5:
                issues.append(f"High duplicate percentage: {duplicate_percentage:.2f}%")
        
        return issues

    async def analyze_database_quality(self) -> Dict[str, Any]:
        """Analyze quality for entire database"""
        schema = await self.database.get_schema()
        tables = schema.get("tables", [])
        
        results = []
        for table in tables:
            result = await self.analyze_table_quality(table)
            results.append(result)
        
        overall_score = sum(r.get("quality_score", 0) for r in results) / len(results) if results else 0
        
        return {
            "overall_quality_score": overall_score,
            "tables_analyzed": len(results),
            "results": results,
        }

