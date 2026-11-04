"""RLS audit — PostgreSQL row level security findings.

Reads ``pg_class``, ``pg_policies`` and ``pg_proc`` on the connection the
operator already opened. A missing privilege is ``not_available``. SQLite and
MySQL have no row level security catalog, so they are ``not_available`` too
rather than an empty "all clear".

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
``license.product_id`` is ``PREMIUM_PRODUCT_IDS["rls-audit"]["monthly"]``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "rls-audit"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"
_SKIP_SCHEMAS = frozenset({"pg_catalog", "information_schema"})

_TABLES_SQL = """
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2
"""

_POLICIES_SQL = """
SELECT schemaname AS schema_name,
       tablename AS table_name,
       policyname AS policy_name,
       permissive,
       cmd,
       qual,
       with_check
FROM pg_policies
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2, 3
"""

_DEFINER_SQL = """
SELECT n.nspname AS schema_name,
       p.proname AS function_name
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.prosecdef
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2
"""


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="RLS audit",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Find PostgreSQL tables without row level security, "
            "permissive policies, and SECURITY DEFINER functions"
        ),
        plugin_type=PluginType.PERFORMANCE_MONITORING,
        plugin_id=PLUGIN_ID,
    )


def _engine_name(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    raw = getattr(config, "type", None) if config is not None else None
    if raw is None and isinstance(connection, dict):
        raw = connection.get("type")
    if raw is None:
        return None
    name = str(raw).strip().lower()
    if name in {"postgres", "supabase"}:
        return "postgresql"
    return name


def _is_true_expr(expr: Any) -> bool:
    if expr is None:
        return False
    text = str(expr).strip().lower()
    return text in {"true", "(true)"}


def _policy_is_open(policy: Dict[str, Any]) -> bool:
    """Permissive policy that allows every row, or has no expression at all."""
    kind = str(policy.get("permissive") or "PERMISSIVE").upper()
    if kind != "PERMISSIVE":
        return False
    qual = policy.get("qual")
    check = policy.get("with_check")
    if qual is None and check is None:
        return True
    return _is_true_expr(qual) or _is_true_expr(check)


def classify_rls(
    tables: Iterable[Dict[str, Any]],
    policies: Iterable[Dict[str, Any]],
    functions: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Turn catalog rows into findings. Does not query a database."""
    unprotected = []
    for table in tables:
        schema = str(table.get("schema_name") or "public")
        if schema in _SKIP_SCHEMAS:
            continue
        enabled = table.get("rls_enabled")
        if enabled in (False, 0, "f", "false", "False"):
            unprotected.append(
                {
                    "schema": schema,
                    "table": str(table.get("table_name")),
                    "rls_forced": bool(table.get("rls_forced")),
                }
            )
    open_policies = []
    for policy in policies:
        schema = str(policy.get("schema_name") or "public")
        if schema in _SKIP_SCHEMAS or not _policy_is_open(policy):
            continue
        open_policies.append(
            {
                "schema": schema,
                "table": str(policy.get("table_name")),
                "policy": str(policy.get("policy_name")),
                "command": str(policy.get("cmd") or "ALL"),
            }
        )
    definers = []
    for fn in functions:
        schema = str(fn.get("schema_name") or "public")
        if schema in _SKIP_SCHEMAS:
            continue
        definers.append(
            {"schema": schema, "function": str(fn.get("function_name"))}
        )
    findings = bool(unprotected or open_policies or definers)
    return {
        "ok": True,
        "status": "fail" if findings else "ok",
        "unprotected_tables": unprotected,
        "permissive_policies": open_policies,
        "security_definer_functions": definers,
        "permission": RUN_PERMISSION,
    }


def _unavailable(engine: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_available",
        "engine": engine,
        "reason": reason,
        "permission": RUN_PERMISSION,
    }


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _query(connection: Any, sql: str) -> List[Dict[str, Any]]:
    raw = getattr(connection, "connection", None)
    if raw is None and hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
    if raw is None:
        raise RuntimeError("database connection is not open")
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        description = cursor.description or []
        columns = [col[0] for col in description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _permission_denied(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "permission denied" in text or "42501" in text or "not authorized" in text


class RlsAuditPlugin(Plugin):
    """Premium plugin: PostgreSQL RLS, open policies, SECURITY DEFINER."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, connection: Any = None, **_kwargs: Any) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        engine = _engine_name(connection)
        if connection is None:
            return _unavailable(None, "A database connection is required")
        if engine != "postgresql":
            return _unavailable(
                engine,
                "Row level security is a PostgreSQL catalog. "
                + (
                    f"This connection is {engine}."
                    if engine
                    else "A connection type is required."
                ),
            )
        try:
            tables = _query(connection, _TABLES_SQL)
            policies = _query(connection, _POLICIES_SQL)
            functions = _query(connection, _DEFINER_SQL)
        except Exception as exc:
            if _permission_denied(exc):
                return _unavailable(engine, "Not available on this role: " + str(exc))
            return _unavailable(engine, str(exc))
        report = classify_rls(tables, policies, functions)
        report["engine"] = engine
        return report

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = RlsAuditPlugin
