"""
Advanced database analysis features
"""

from .performance import QueryPerformanceAnalyzer
from .optimization import IndexOptimizer
from .prediction import StorageGrowthPredictor
from .capacity import CapacityPlanner
from .query_suggestions import (
    QuerySuggestion,
    analyze_explain_plan,
    analyze_sql_heuristics,
    fetch_explain_plan,
    suggest_for_query,
)

__all__ = [
    "QueryPerformanceAnalyzer",
    "IndexOptimizer",
    "StorageGrowthPredictor",
    "CapacityPlanner",
    "QuerySuggestion",
    "analyze_sql_heuristics",
    "analyze_explain_plan",
    "fetch_explain_plan",
    "suggest_for_query",
]
