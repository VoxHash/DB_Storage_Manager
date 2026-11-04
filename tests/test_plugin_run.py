"""Real migration, data comparison, and the Plugins Run path."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.factory import DatabaseConnectionFactory
from db_storage_manager.plugins.data_comparison import DataComparisonPlugin
from db_storage_manager.plugins.invoke import (
    MULTI_CLOUD_ID,
    SPECS,
    execute_plan,
    format_plugin_result,
    plan_run,
)
from db_storage_manager.plugins.live_tables import (
    create_table_sql,
    format_data_type,
)
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.migration import MigrationPlugin
from db_storage_manager.security.auth import (
    AuthenticationManager,
    UserRole,
    reset_auth_manager,
)

ROOT = Path(__file__).resolve().parents[1]
PREMIUM = ROOT / "db_storage_manager" / "premium_plugins"
SECRET = "s3cret-value"
PAYLOAD = "DSMENC1abcdef"


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "AUDIT_LOG_FILE", path)
    return path


def _seed(path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, note TEXT, password TEXT)"
    )
    connection.executemany("INSERT INTO items VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute("SELECT id, note, password FROM items"))
    finally:
        connection.close()


def _sqlite(path: Path, name: str) -> object:
    return DatabaseConnectionFactory.create_connection(
        ConnectionConfig(
            id=name,
            name=name,
            type="sqlite",
            database=str(path),
            password=SECRET,
        )
    )


def _profiles(source: Path, target: Path) -> list[dict]:
    return [
        {
            "id": "src",
            "name": "source",
            "type": "sqlite",
            "database": str(source),
            "password": SECRET,
        },
        {
            "id": "dst",
            "name": "target",
            "type": "sqlite",
            "database": str(target),
            "password": SECRET,
        },
    ]


def test_migration_copies_rows_and_hides_secrets(
    tmp_path, audit_log, marketplace
):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, "alpha", SECRET), (2, PAYLOAD, "other")])
    sqlite3.connect(target).close()
    plugin = MigrationPlugin()
    result = plugin.execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        tables=["items"],
    )
    assert result["status"] == "success"
    assert result["tables_migrated"] == ["items"]
    assert _rows(target) == [(1, "alpha", SECRET), (2, PAYLOAD, "other")]
    text = json.dumps(result)
    assert PAYLOAD not in text
    assert SECRET not in text
    audit = audit_log.read_text(encoding="utf-8")
    assert "plugin.migration" in audit
    assert PAYLOAD not in audit
    assert SECRET not in audit


def test_migration_does_not_replace_without_confirmation(
    tmp_path, audit_log, marketplace
):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, "alpha", SECRET)])
    _seed(target, [(9, "keep", "stay")])
    plugin = MigrationPlugin()
    refused = plugin.execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        tables=["items"],
        replace=True,
        confirm="nope",
    )
    assert refused["status"] == "not_available"
    assert _rows(target) == [(9, "keep", "stay")]
    phrase = "target.db"
    replaced = plugin.execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        tables=["items"],
        replace=True,
        confirm=phrase,
    )
    assert replaced["status"] == "success"
    assert _rows(target) == [(1, "alpha", SECRET)]
    skipped = plugin.execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        tables=["items"],
    )
    assert skipped["tables"][0]["action"] == "skipped"
    assert _rows(target) == [(1, "alpha", SECRET)]


def test_migration_refuses_other_engines_and_the_same_file(
    tmp_path, audit_log, marketplace
):
    source = tmp_path / "source.db"
    _seed(source, [(1, "alpha", SECRET)])
    plugin = MigrationPlugin()
    mongo = DatabaseConnectionFactory.create_connection(
        ConnectionConfig(id="m", name="m", type="mongodb", database="app")
    )
    refused = plugin.execute(
        _sqlite(source, "source"), mongo, tables=["items"]
    )
    assert refused["status"] == "not_available"
    assert mongo.connected is False
    same = plugin.execute(
        _sqlite(source, "source"),
        _sqlite(source, "again"),
        tables=["items"],
    )
    assert same["status"] == "not_available"
    assert "same database" in same["reason"]


def test_viewer_cannot_migrate(tmp_path, audit_log, marketplace, monkeypatch):
    _mp, store, _plugins = marketplace
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("viewer1", "password123", role=UserRole.VIEWER)
    auth.logout()
    assert auth.authenticate("viewer1", "password123")
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_auth_manager", auth)
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, "alpha", SECRET)])
    sqlite3.connect(target).close()
    result = MigrationPlugin().execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        tables=["items"],
    )
    assert result["status"] == "not_available"
    assert "query:" in result["reason"]
    assert not _table_exists(target, "items")
    reset_auth_manager()


def test_data_comparison_reports_diffs_and_redacts(
    tmp_path, audit_log, marketplace
):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, PAYLOAD, SECRET)])
    _seed(target, [(1, "other", SECRET)])
    result = DataComparisonPlugin().execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        "items",
    )
    assert result["status"] == "diff"
    assert result["matches"] == 0
    assert result["mismatches"] == 2
    text = json.dumps(result)
    assert PAYLOAD not in text
    assert SECRET not in text
    assert "[redacted]" in text
    audit = audit_log.read_text(encoding="utf-8")
    assert "plugin.data_comparison" in audit
    assert PAYLOAD not in audit
    assert SECRET not in audit
    missing = DataComparisonPlugin().execute(
        _sqlite(source, "source"),
        _sqlite(target, "target"),
        "absent",
    )
    assert missing["status"] == "not_available"


def test_postgres_create_refuses_an_unsafe_type():
    sql = create_table_sql(
        "postgresql",
        "items",
        [
            {"name": "id", "type": "integer", "nullable": False},
            {"name": "note", "type": "text", "nullable": True},
        ],
    )
    assert sql == ('CREATE TABLE "items" ("id" integer NOT NULL, "note" text)')
    assert format_data_type({"data_type": "USER-DEFINED"}) is None
    with pytest.raises(ValueError):
        create_table_sql(
            "mysql",
            "items",
            [
                {
                    "name": "id",
                    "type": "int; drop table items",
                    "nullable": True,
                }
            ],
        )


def test_execute_plan_copies_and_blocks_an_unlicensed_plugin(
    tmp_path, audit_log, marketplace
):
    mp, _store, _plugins = marketplace
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, "alpha", SECRET)])
    sqlite3.connect(target).close()
    mp.sync_builtins()
    mp.load_into_manager()
    profiles = _profiles(source, target)
    plan = plan_run(
        "migration",
        {
            "source_id": "src",
            "target_id": "dst",
            "tables": "items",
            "replace": False,
            "confirm": "",
        },
    )
    result = execute_plan(mp, plan, profiles)
    assert result["status"] == "success"
    assert _rows(target) == [(1, "alpha", SECRET)]
    assert SECRET not in json.dumps(result)

    manifest = load_manifest(PREMIUM / "rls-audit")
    data = mp._read_registry()
    data["plugins"]["rls-audit"] = {
        "id": "rls-audit",
        "source": "path",
        "module": None,
        "path": str(PREMIUM / "rls-audit"),
        "origin": str(PREMIUM / "rls-audit"),
        "installed_at": "2026-11-04T00:00:00+00:00",
        "manifest": manifest.to_dict(),
    }
    mp._write_registry(data)
    blocked = execute_plan(
        mp,
        plan_run("rls-audit", {"source_id": "src", "target_id": ""}),
        profiles,
    )
    assert blocked["status"] == "not_available"
    assert mp.manager.get_plugin("rls-audit") is None


def test_run_specs_cover_premium_plugins_except_discovery():
    ids = {path.parent.name for path in PREMIUM.glob("*/plugin.json")}
    assert MULTI_CLOUD_ID in ids
    assert ids - {MULTI_CLOUD_ID} == set(SPECS) - {
        "migration",
        "data_comparison",
    }
    plan = plan_run(MULTI_CLOUD_ID, {})
    assert plan.blocked
    assert "Discover Cloud" in plan.blocked
    shown = format_plugin_result(
        {"status": "ok", "passphrase": SECRET, "note": PAYLOAD}
    )
    assert SECRET not in shown
    assert PAYLOAD not in shown
    assert "[redacted]" in shown


def test_sqlite_premium_plugin_runs_through_the_saved_connection(
    tmp_path, marketplace
):
    source = tmp_path / "source.db"
    _seed(source, [(1, "alpha", SECRET)])
    profile = _profiles(source, source)[0]
    from db_storage_manager.plugins.live_tables import connection_from_profile

    connection = connection_from_profile(profile)
    plugin = load_plugin_from_directory(PREMIUM / "schema-drift")
    result = plugin.execute(connection=connection)
    assert result["status"] == "snapshot"
    assert "items" in result["snapshot"]["tables"]
    rls = load_plugin_from_directory(PREMIUM / "rls-audit")
    unavailable = rls.execute(connection=connection)
    assert unavailable["status"] == "not_available"


def test_plugins_run_dialog_copies(
    tmp_path, audit_log, marketplace, monkeypatch
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from db_storage_manager.gui.plugin_run import PluginRunDialog
    from db_storage_manager.gui.plugins import PluginsWidget

    mp, _store, _plugins = marketplace
    mp.sync_builtins()
    mp.load_into_manager()
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed(source, [(1, PAYLOAD, SECRET)])
    sqlite3.connect(target).close()
    app = QApplication.instance() or QApplication([])
    widget = PluginsWidget(marketplace=mp)
    assert widget.run_btn.text()
    dialog = PluginRunDialog("migration", _profiles(source, target), mp)
    dialog.show()
    dialog.tables_edit.setText("items")
    dialog.target_combo.setCurrentIndex(1)
    assert dialog.run_plan().connection_ids == {
        "source_db": "src",
        "target_db": "dst",
    }
    dialog.run_btn.click()
    text = ""
    for _ in range(100):
        app.processEvents()
        text = dialog.result_box.toPlainText()
        if text:
            break
        time.sleep(0.05)
    assert "success" in text
    assert PAYLOAD not in text
    assert SECRET not in text
    assert _rows(target) == [(1, PAYLOAD, SECRET)]
    dialog.close()
    widget.close()


def _table_exists(path: Path, name: str) -> bool:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()
