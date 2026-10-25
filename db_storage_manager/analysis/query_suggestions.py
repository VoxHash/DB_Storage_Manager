"""
Query optimization suggestions from SQL heuristics and EXPLAIN plans.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from ..db.base import DatabaseConnection


@dataclass(frozen=True)
class QuerySuggestion:
    """One actionable optimization suggestion."""

    code: str
    severity: str  # high | medium | low | info
    title: str
    message: str
    source: str  # heuristic | explain

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


_SELECT_STAR_RE = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?\*(?=\s|,|$)", re.IGNORECASE | re.DOTALL
)
_LEADING_LIKE_RE = re.compile(
    r"\bLIKE\s+(['\"])%[^'\"]*\1", re.IGNORECASE
)
_ORDER_WITHOUT_LIMIT_RE = re.compile(
    r"\bORDER\s+BY\b(?![\s\S]*\bLIMIT\b)", re.IGNORECASE
)
_WHERE_FUNC_COL_RE = re.compile(
    r"\bWHERE\b[\s\S]*?\b(?:LOWER|UPPER|TRIM|ABS|CAST)\s*\(\s*[\w.]+",
    re.IGNORECASE,
)
_OR_IN_WHERE_RE = re.compile(
    r"\bWHERE\b[\s\S]*?\bOR\b", re.IGNORECASE
)
_FROM_NO_WHERE_RE = re.compile(
    r"\bFROM\b(?![\s\S]*\bWHERE\b)", re.IGNORECASE | re.DOTALL
)
_NOT_IN_RE = re.compile(r"\bNOT\s+IN\s*\(", re.IGNORECASE)


def is_read_query(query: str) -> bool:
    """True when the statement is a SELECT (Safe Mode–compatible)."""
    return bool(query) and query.strip().upper().startswith("SELECT")


def analyze_sql_heuristics(query: str) -> List[QuerySuggestion]:
    """Produce suggestions from SQL text alone (no database required)."""
    sql = (query or "").strip()
    if not sql:
        return []

    suggestions: List[QuerySuggestion] = []

    if _SELECT_STAR_RE.search(sql):
        suggestions.append(
            QuerySuggestion(
                code="select_star",
                severity="medium",
                title="Avoid SELECT *",
                message=(
                    "Selecting all columns can pull unused data and prevent "
                    "covering-index plans. List only the columns you need."
                ),
                source="heuristic",
            )
        )

    if _LEADING_LIKE_RE.search(sql):
        suggestions.append(
            QuerySuggestion(
                code="leading_wildcard_like",
                severity="high",
                title="Leading wildcard in LIKE",
                message=(
                    "Patterns like LIKE '%value' typically disable index prefix "
                    "matches. Prefer trailing wildcards, full-text search, or "
                    "normalized lookup columns when possible."
                ),
                source="heuristic",
            )
        )

    if is_read_query(sql) and _FROM_NO_WHERE_RE.search(sql):
        # Skip trivial single-row metadata style if LIMIT 1 only — still warn
        suggestions.append(
            QuerySuggestion(
                code="missing_where",
                severity="medium",
                title="No WHERE clause",
                message=(
                    "This SELECT has no WHERE filter. Confirm a full scan is "
                    "intentional; add predicates or LIMIT for large tables."
                ),
                source="heuristic",
            )
        )

    if _ORDER_WITHOUT_LIMIT_RE.search(sql) and is_read_query(sql):
        suggestions.append(
            QuerySuggestion(
                code="order_without_limit",
                severity="low",
                title="ORDER BY without LIMIT",
                message=(
                    "Sorting the full result set can be expensive. Add LIMIT "
                    "when only a page of rows is needed, or index ORDER BY columns."
                ),
                source="heuristic",
            )
        )

    if _WHERE_FUNC_COL_RE.search(sql):
        suggestions.append(
            QuerySuggestion(
                code="function_on_column",
                severity="medium",
                title="Function wrapped column in WHERE",
                message=(
                    "Wrapping a column in LOWER/UPPER/CAST (etc.) often blocks "
                    "plain index use. Prefer functional/expression indexes or "
                    "store a normalized column."
                ),
                source="heuristic",
            )
        )

    if _OR_IN_WHERE_RE.search(sql):
        suggestions.append(
            QuerySuggestion(
                code="or_in_where",
                severity="low",
                title="OR in WHERE clause",
                message=(
                    "OR predicates can prevent a single index range scan. "
                    "Consider UNION ALL of indexed branches or redesign filters."
                ),
                source="heuristic",
            )
        )

    if _NOT_IN_RE.search(sql):
        suggestions.append(
            QuerySuggestion(
                code="not_in",
                severity="low",
                title="NOT IN predicate",
                message=(
                    "NOT IN can be slow or NULL-sensitive. Prefer NOT EXISTS "
                    "or anti-join patterns when correlating to another set."
                ),
                source="heuristic",
            )
        )

    return _dedupe(suggestions)


def analyze_explain_plan(
    explain_plan: Any, db_type: str = "sqlite"
) -> List[QuerySuggestion]:
    """Turn engine EXPLAIN output into actionable suggestions."""
    if explain_plan is None:
        return []

    db = (db_type or "sqlite").lower()
    text = _plan_to_text(explain_plan)
    if not text:
        return []

    lower = text.lower()
    suggestions: List[QuerySuggestion] = []

    if db in ("sqlite",):
        suggestions.extend(_analyze_sqlite_plan(explain_plan, lower))
    elif db in ("postgresql", "postgres"):
        suggestions.extend(_analyze_postgres_plan(lower))
    elif db in ("mysql", "mariadb"):
        suggestions.extend(_analyze_mysql_plan(explain_plan, lower))
    else:
        # Generic cues shared across SQL engines
        if "seq scan" in lower or "sequential scan" in lower:
            suggestions.append(
                QuerySuggestion(
                    code="seq_scan",
                    severity="medium",
                    title="Sequential / full table scan",
                    message=(
                        "The plan shows a sequential scan. Add or adjust indexes "
                        "on filter/join columns if the table is large."
                    ),
                    source="explain",
                )
            )

    return _dedupe(suggestions)


async def fetch_explain_plan(
    connection: DatabaseConnection,
    query: str,
    *,
    safe_mode: bool = True,
) -> Optional[Any]:
    """
    Run a read-only EXPLAIN for ``query`` when Safe Mode allows it.

    Under Safe Mode, only SELECT statements are explained. EXPLAIN itself is
    issued through the live connection (SQLite uses the aiosqlite handle so
    Safe Mode's SELECT-only gate does not block the EXPLAIN wrapper).
    """
    sql = (query or "").strip()
    if not sql:
        return None

    if safe_mode and not is_read_query(sql):
        return None

    if not connection.connected:
        await connection.connect()

    db_type = connection.config.type.lower()

    if db_type == "sqlite":
        raw = getattr(connection, "connection", None)
        if raw is None:
            return None
        cursor = await raw.execute(f"EXPLAIN QUERY PLAN {sql}")
        rows = await cursor.fetchall()
        # aiosqlite Row or tuple: (id, parent, notused, detail) in modern SQLite
        return [list(row) for row in rows]

    if db_type in ("postgresql", "postgres"):
        # EXPLAIN is read-only; bypass SELECT-only gate for the wrapper only
        result = await connection.execute_query(f"EXPLAIN {sql}", safe_mode=False)
        return result.get("rows") or result.get("explainPlan")

    if db_type in ("mysql", "mariadb"):
        result = await connection.execute_query(f"EXPLAIN {sql}", safe_mode=False)
        return result.get("rows") or result.get("explainPlan")

    return None


async def suggest_for_query(
    query: str,
    *,
    connection: Optional[DatabaseConnection] = None,
    explain_plan: Any = None,
    safe_mode: bool = True,
    db_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Combine heuristic and EXPLAIN-based suggestions.

    Prefer a provided ``explain_plan`` (e.g. from ``execute_query``). Otherwise,
    when ``connection`` is set, fetch a live plan with Safe Mode respected.
    """
    sql = (query or "").strip()
    heuristics = analyze_sql_heuristics(sql)

    resolved_type = (
        db_type
        or (connection.config.type if connection is not None else None)
        or "sqlite"
    ).lower()

    plan = explain_plan
    explain_error: Optional[str] = None
    explain_skipped_safe_mode = False

    if plan is None and connection is not None and sql:
        if safe_mode and not is_read_query(sql):
            explain_skipped_safe_mode = True
        else:
            try:
                plan = await fetch_explain_plan(
                    connection, sql, safe_mode=safe_mode
                )
            except Exception as exc:  # pragma: no cover - engine-specific failures
                explain_error = str(exc)
                plan = None

    explain_suggestions = analyze_explain_plan(plan, resolved_type)
    combined = _dedupe(heuristics + explain_suggestions)

    return {
        "suggestions": [s.to_dict() for s in combined],
        "explainPlan": plan,
        "explainError": explain_error,
        "explainSkippedSafeMode": explain_skipped_safe_mode,
        "dbType": resolved_type,
        "counts": {
            "total": len(combined),
            "heuristic": len(heuristics),
            "explain": len(explain_suggestions),
            "high": sum(1 for s in combined if s.severity == "high"),
            "medium": sum(1 for s in combined if s.severity == "medium"),
            "low": sum(1 for s in combined if s.severity == "low"),
        },
    }


def _dedupe(items: Sequence[QuerySuggestion]) -> List[QuerySuggestion]:
    seen = set()
    out: List[QuerySuggestion] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        out.append(item)
    return out


def _plan_to_text(explain_plan: Any) -> str:
    if isinstance(explain_plan, str):
        return explain_plan
    if isinstance(explain_plan, dict):
        return str(explain_plan)
    if isinstance(explain_plan, (list, tuple)):
        parts: List[str] = []
        for row in explain_plan:
            if isinstance(row, dict):
                detail = row.get("detail") or row.get("QUERY PLAN") or row.get("Extra")
                if detail is None:
                    parts.append(" ".join(str(v) for v in row.values()))
                else:
                    parts.append(str(detail))
            elif isinstance(row, (list, tuple)):
                # SQLite: last column is usually detail
                parts.append(" ".join(str(c) for c in row))
            else:
                parts.append(str(row))
        return "\n".join(parts)
    return str(explain_plan)


def _sqlite_details(explain_plan: Any) -> List[str]:
    details: List[str] = []
    if not isinstance(explain_plan, (list, tuple)):
        return [_plan_to_text(explain_plan)]
    for row in explain_plan:
        if isinstance(row, dict):
            details.append(str(row.get("detail", row)))
        elif isinstance(row, (list, tuple)) and row:
            details.append(str(row[-1]))
        else:
            details.append(str(row))
    return details


def _analyze_sqlite_plan(
    explain_plan: Any, lower_text: str
) -> List[QuerySuggestion]:
    suggestions: List[QuerySuggestion] = []
    details = [d.lower() for d in _sqlite_details(explain_plan)]

    has_scan_without_index = any(
        ("scan " in d or d.startswith("scan"))
        and "using index" not in d
        and "using covering index" not in d
        and "using integer primary key" not in d
        for d in details
    )
    if has_scan_without_index or (
        "scan " in lower_text and "using index" not in lower_text
    ):
        suggestions.append(
            QuerySuggestion(
                code="sqlite_table_scan",
                severity="medium",
                title="Table scan in query plan",
                message=(
                    "EXPLAIN QUERY PLAN reports a SCAN without an index. "
                    "Add an index matching WHERE/JOIN columns if the table is large."
                ),
                source="explain",
            )
        )

    if "use temp b-tree" in lower_text:
        suggestions.append(
            QuerySuggestion(
                code="sqlite_temp_btree",
                severity="medium",
                title="Temporary B-tree for sort/group",
                message=(
                    "SQLite is building a temporary B-tree for ORDER BY, GROUP BY, "
                    "or DISTINCT. An index on those columns can avoid the extra sort."
                ),
                source="explain",
            )
        )

    if "automatic" in lower_text and "index" in lower_text:
        suggestions.append(
            QuerySuggestion(
                code="sqlite_auto_index",
                severity="high",
                title="Automatic transient index",
                message=(
                    "The planner is creating an automatic index for this statement. "
                    "Create a permanent index on the join/filter columns to avoid "
                    "rebuilding it on every execution."
                ),
                source="explain",
            )
        )

    return suggestions


def _analyze_postgres_plan(lower_text: str) -> List[QuerySuggestion]:
    suggestions: List[QuerySuggestion] = []
    if "seq scan" in lower_text:
        suggestions.append(
            QuerySuggestion(
                code="pg_seq_scan",
                severity="medium",
                title="Sequential scan",
                message=(
                    "PostgreSQL plans a Seq Scan. Consider indexes on filter and "
                    "join keys, and ensure statistics are up to date (ANALYZE)."
                ),
                source="explain",
            )
        )
    if "sort" in lower_text and "index" not in lower_text:
        suggestions.append(
            QuerySuggestion(
                code="pg_sort",
                severity="low",
                title="Explicit sort step",
                message=(
                    "The plan includes a Sort node. An index matching ORDER BY "
                    "can often remove this step for large results."
                ),
                source="explain",
            )
        )
    return suggestions


def _analyze_mysql_plan(
    explain_plan: Any, lower_text: str
) -> List[QuerySuggestion]:
    suggestions: List[QuerySuggestion] = []
    rows = explain_plan if isinstance(explain_plan, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        access = str(row.get("type", "")).lower()
        extra = str(row.get("Extra", "")).lower()
        if access in ("all",):
            suggestions.append(
                QuerySuggestion(
                    code="mysql_full_scan",
                    severity="medium",
                    title="Full table access (type=ALL)",
                    message=(
                        f"MySQL access type ALL on table "
                        f"{row.get('table', '?')}. Add an index for the "
                        "filter/join columns when the table is non-trivial."
                    ),
                    source="explain",
                )
            )
        if "using filesort" in extra:
            suggestions.append(
                QuerySuggestion(
                    code="mysql_filesort",
                    severity="low",
                    title="Using filesort",
                    message=(
                        "EXPLAIN Extra reports Using filesort. Index the ORDER BY "
                        "columns to avoid an extra sort."
                    ),
                    source="explain",
                )
            )
        if "using temporary" in extra:
            suggestions.append(
                QuerySuggestion(
                    code="mysql_temporary",
                    severity="medium",
                    title="Using temporary table",
                    message=(
                        "EXPLAIN Extra reports Using temporary. Simplify GROUP BY / "
                        "DISTINCT or add supporting indexes."
                    ),
                    source="explain",
                )
            )
    if not suggestions and "type=all" in lower_text.replace(" ", ""):
        suggestions.append(
            QuerySuggestion(
                code="mysql_full_scan",
                severity="medium",
                title="Full table access (type=ALL)",
                message=(
                    "MySQL plan indicates a full table scan. Review indexes on "
                    "filtered columns."
                ),
                source="explain",
            )
        )
    return _dedupe(suggestions)
