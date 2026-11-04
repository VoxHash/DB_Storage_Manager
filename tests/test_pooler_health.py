"""Pooler health compares recorded probes and refuses to invent a pooler."""

from __future__ import annotations

import sqlite3

from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.pricing import PREMIUM_PRODUCT_IDS, PRICING_TIERS
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import AuthenticationManager

PLUGIN_DIR = bundled_plugin_dir("pooler-health")


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pooler_health_under_test", PLUGIN_DIR / "plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_uses_the_monthly_product():
    manifest = load_manifest(PLUGIN_DIR)
    monthly = PREMIUM_PRODUCT_IDS["pooler-health"]["monthly"]
    assert manifest.license is not None
    assert manifest.license.product_id == monthly
    assert manifest.license.pricing["yearly"] == PRICING_TIERS["plugin"]["yearly"]


def test_assess_reports_headroom_and_does_not_guess_a_pooler():
    module = _module()
    direct = {
        "ok": True,
        "status": "ok",
        "latency_ms": 4.0,
        "max_connections": 100,
        "active": 12,
        "pool_mode": None,
        "pool_mode_status": "not_available",
    }
    pooled = {
        "ok": True,
        "status": "ok",
        "latency_ms": 9.5,
        "max_connections": 20,
        "active": 18,
        "pool_mode": "transaction",
        "pool_mode_status": "ok",
    }
    both = module.assess(direct, pooled)
    assert both["status"] == "ok"
    assert both["direct"]["headroom"] == 88
    assert both["pooled"]["headroom"] == 2
    assert both["pooled"]["pool_mode"] == "transaction"
    assert both["latency_delta_ms"] == 5.5

    alone = module.assess(direct, None)
    assert alone["status"] == "partial"
    assert alone["pooled"] is None
    assert "not guessed" in alone["reason"]


def test_sqlite_probe_is_not_available(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "_auth_manager", AuthenticationManager(store=store)
    )
    path = tmp_path / "app.db"
    sqlite3.connect(path).close()
    connection = type(
        "Conn",
        (),
        {"config": type("Cfg", (), {"type": "sqlite", "database": str(path)})()},
    )()
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    report = plugin.execute(connection)
    assert report["status"] == "not_available"
    assert "PostgreSQL" in report["reason"]
    sql = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
    assert "max_connections" in sql and "SHOW pool_mode" in sql
