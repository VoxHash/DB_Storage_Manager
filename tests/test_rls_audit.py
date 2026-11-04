"""RLS audit: real catalog shape, SQLite is not a guess of 'no findings'."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.pricing import PREMIUM_PRODUCT_IDS, PRICING_TIERS
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import AuthenticationManager

PLUGIN_DIR = bundled_plugin_dir("rls-audit")


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rls_audit_under_test", PLUGIN_DIR / "plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_uses_the_monthly_product():
    manifest = load_manifest(PLUGIN_DIR)
    monthly = PREMIUM_PRODUCT_IDS["rls-audit"]["monthly"]
    assert manifest.license is not None
    assert manifest.license.product_id == monthly
    assert manifest.license.pricing["monthly"] == PRICING_TIERS["plugin"]["monthly"]


def test_classify_flags_unprotected_tables_open_policies_and_definers():
    module = _module()
    report = module.classify_rls(
        tables=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "rls_enabled": False,
                "rls_forced": False,
            },
            {
                "schema_name": "public",
                "table_name": "profiles",
                "rls_enabled": True,
                "rls_forced": True,
            },
            {
                "schema_name": "pg_catalog",
                "table_name": "pg_class",
                "rls_enabled": False,
                "rls_forced": False,
            },
        ],
        policies=[
            {
                "schema_name": "public",
                "table_name": "profiles",
                "policy_name": "open_read",
                "permissive": "PERMISSIVE",
                "cmd": "SELECT",
                "qual": "true",
                "with_check": None,
            },
            {
                "schema_name": "public",
                "table_name": "profiles",
                "policy_name": "own_row",
                "permissive": "PERMISSIVE",
                "cmd": "ALL",
                "qual": "(user_id = auth.uid())",
                "with_check": None,
            },
        ],
        functions=[
            {"schema_name": "public", "function_name": "admin_delete"},
            {"schema_name": "pg_catalog", "function_name": "now"},
        ],
    )
    assert report["status"] == "fail"
    assert report["unprotected_tables"] == [
        {"schema": "public", "table": "orders", "rls_forced": False}
    ]
    assert report["permissive_policies"] == [
        {
            "schema": "public",
            "table": "profiles",
            "policy": "open_read",
            "command": "SELECT",
        }
    ]
    assert report["security_definer_functions"] == [
        {"schema": "public", "function": "admin_delete"}
    ]
    sql = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
    assert "pg_class" in sql and "pg_policies" in sql and "prosecdef" in sql


def test_sqlite_is_not_available(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "_auth_manager", AuthenticationManager(store=store)
    )
    path = tmp_path / "app.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER)")
    connection = type(
        "Conn",
        (),
        {"config": type("Cfg", (), {"type": "sqlite", "database": str(path)})()},
    )()
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    report = plugin.execute(connection)
    assert report["status"] == "not_available"
    assert report["ok"] is False
    assert "PostgreSQL" in report["reason"]
