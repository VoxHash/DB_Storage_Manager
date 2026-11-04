"""Schema drift premium plugin: real SQLite catalogs, no placeholders."""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.sqlite import SQLiteConnection
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.pricing import PREMIUM_PRODUCT_IDS, PRICING_TIERS
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
    reset_auth_manager,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = bundled_plugin_dir("schema-drift")


def _module():
    spec = importlib.util.spec_from_file_location(
        "schema_drift_under_test", PLUGIN_DIR / "plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _seed(path: Path, extra_column: bool = False) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY NOT NULL, name TEXT)"
        )
        if extra_column:
            conn.execute("ALTER TABLE items ADD COLUMN note TEXT")
        conn.execute("INSERT INTO items(name) VALUES ('alpha')")
        conn.commit()
    finally:
        conn.close()


def _open(path: Path) -> SQLiteConnection:
    cfg = ConnectionConfig(
        id=f"drift-{path.name}", name=path.name, type="sqlite", database=str(path)
    )
    conn = SQLiteConnection(cfg)
    asyncio.run(conn.connect())
    return conn


def test_manifest_uses_the_monthly_product():
    manifest = load_manifest(PLUGIN_DIR)
    monthly = PREMIUM_PRODUCT_IDS["schema-drift"]["monthly"]
    assert manifest.license is not None
    assert manifest.license.product_id == monthly
    assert manifest.license.pricing["monthly"] == PRICING_TIERS["plugin"]["monthly"]


def test_snapshot_and_diff_against_another_sqlite_file(
    tmp_path, isolated_secure_store, monkeypatch
):
    store, _ = isolated_secure_store
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "_auth_manager", AuthenticationManager(store=store)
    )
    baseline = tmp_path / "base.db"
    current = tmp_path / "current.db"
    _seed(baseline)
    _seed(current, extra_column=True)
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    assert plugin.initialize({}) is True
    report = plugin.execute(_open(current), other=_open(baseline))
    assert report["ok"] is True
    assert report["status"] == "diff"
    diff = report["diff"]
    assert diff["tables_added"] == []
    assert diff["tables_removed"] == []
    assert diff["changed"] is True
    added = diff["columns_added"]
    assert len(added) == 1
    assert added[0]["table"] == "items"
    assert added[0]["column"] == "note"

    same = plugin.execute(_open(baseline), other=_open(baseline))
    assert same["diff"]["changed"] is False

    snapshot = plugin.execute(_open(current))
    assert snapshot["status"] == "snapshot"
    assert "items" in snapshot["snapshot"]["tables"]


def test_saved_baseline_dict_is_diffed():
    module = _module()
    baseline = {
        "engine": "sqlite",
        "tables": {
            "items": {
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False},
                ]
            }
        },
    }
    current = {
        "engine": "sqlite",
        "tables": {
            "items": {
                "columns": [
                    {"name": "id", "type": "text", "nullable": False},
                    {"name": "name", "type": "text", "nullable": True},
                ]
            },
            "extra": {"columns": []},
        },
    }
    diff = module.diff_snapshots(baseline, current)
    assert diff["tables_added"] == ["extra"]
    assert diff["columns_added"][0]["column"] == "name"
    assert diff["columns_changed"][0]["column"] == "id"
    assert diff["columns_changed"][0]["before"]["type"] == "integer"
    assert diff["columns_changed"][0]["after"]["type"] == "text"


def test_guest_cannot_run_schema_drift(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("guest1", "password123", role=UserRole.GUEST)
    auth.logout()
    auth.authenticate("guest1", "password123")
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_auth_manager", auth)
    path = tmp_path / "view.db"
    _seed(path)
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    with pytest.raises(PermissionDenied):
        plugin.execute(_open(path))
    reset_auth_manager()


def test_licensechain_dry_run_stays_within_policy():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "licensechain_products.py"),
            str(PLUGIN_DIR),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "1.99" in completed.stdout
    assert "dry run" in completed.stderr
