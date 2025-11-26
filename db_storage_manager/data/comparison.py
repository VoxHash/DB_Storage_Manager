"""
Data comparison tools
"""

from typing import Dict, Any, List, Tuple
from ..db.base import DatabaseConnection


class DataComparator:
    """Compare data between databases"""

    def __init__(self, source_db: DatabaseConnection, target_db: DatabaseConnection):
        self.source_db = source_db
        self.target_db = target_db

    async def compare_table(self, table_name: str) -> Dict[str, Any]:
        """Compare a table between source and target"""
        # Get data from source
        source_query = f"SELECT * FROM {table_name} ORDER BY 1"
        source_result = await self.source_db.execute_query(source_query, safe_mode=True)

        # Get data from target
        target_query = f"SELECT * FROM {table_name} ORDER BY 1"
        target_result = await self.target_db.execute_query(target_query, safe_mode=True)

        source_rows = source_result.get("rows", [])
        target_rows = target_result.get("rows", [])

        # Compare
        differences = []
        matches = 0

        # Simple row-by-row comparison
        max_len = max(len(source_rows), len(target_rows))
        for i in range(max_len):
            source_row = source_rows[i] if i < len(source_rows) else None
            target_row = target_rows[i] if i < len(target_rows) else None

            if source_row != target_row:
                differences.append(
                    {
                        "row_index": i,
                        "source": source_row,
                        "target": target_row,
                    }
                )
            else:
                matches += 1

        return {
            "table": table_name,
            "source_count": len(source_rows),
            "target_count": len(target_rows),
            "matches": matches,
            "differences": differences,
            "difference_count": len(differences),
        }

    async def compare_schema(self) -> Dict[str, Any]:
        """Compare schemas between databases"""
        source_schema = await self.source_db.get_schema()
        target_schema = await self.target_db.get_schema()

        source_tables = set(source_schema.get("tables", []))
        target_tables = set(target_schema.get("tables", []))

        return {
            "source_tables": list(source_tables),
            "target_tables": list(target_tables),
            "common_tables": list(source_tables & target_tables),
            "only_in_source": list(source_tables - target_tables),
            "only_in_target": list(target_tables - source_tables),
        }
