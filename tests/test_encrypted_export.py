"""Encrypted export writes a real SQLite table into DSMENC1 and redacts a column."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db_storage_manager.native import decrypt_file
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.manifest import load_manifest
from db_storage_manager.plugins.pricing import PREMIUM_PRODUCT_IDS, PRICING_TIERS
from db_storage_manager.premium_plugins import bundled_plugin_dir
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
)

PLUGIN_DIR = bundled_plugin_dir("encrypted-export")


def _auth(store, monkeypatch):
    import db_storage_manager.security.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "_auth_manager", AuthenticationManager(store=store)
    )


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT, secret TEXT)"
        )
        conn.execute(
            "INSERT INTO people (name, secret) VALUES ('ada', 's3cret-value')"
        )
        conn.commit()
    finally:
        conn.close()


def _connection(path: Path):
    return type(
        "Conn",
        (),
        {"config": type("Cfg", (), {"type": "sqlite", "database": str(path)})()},
    )()


def test_manifest_uses_the_monthly_product():
    manifest = load_manifest(PLUGIN_DIR)
    monthly = PREMIUM_PRODUCT_IDS["encrypted-export"]["monthly"]
    assert manifest.license is not None
    assert manifest.license.product_id == monthly
    assert manifest.license.pricing["one_time"] == PRICING_TIERS["plugin"]["one_time"]


def test_csv_export_redacts_then_encrypts(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    _auth(store, monkeypatch)
    db = tmp_path / "people.db"
    _seed(db)
    dest = tmp_path / "people.csv.enc"
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    report = plugin.execute(
        _connection(db),
        table="people",
        dest=dest,
        passphrase="correct horse battery",
        format="csv",
        redact=["secret"],
    )
    assert report["ok"] is True
    assert report["rows"] == 1
    assert report["envelope"] == "DSMENC1"
    assert report["redacted_columns"] == ["secret"]
    assert dest.is_file()
    assert not dest.with_name(dest.name + ".plain").exists()
    plain = tmp_path / "out.csv"
    decrypt_file(dest, plain, "correct horse battery")
    text = plain.read_text(encoding="utf-8")
    assert "ada" in text
    assert "s3cret-value" not in text
    assert "REDACTED" in text
    assert "correct horse battery" not in report["path"]


def test_sql_export_and_missing_passphrase(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    _auth(store, monkeypatch)
    db = tmp_path / "people.db"
    _seed(db)
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    dest = tmp_path / "people.sql.enc"
    report = plugin.execute(
        _connection(db),
        table="people",
        dest=dest,
        passphrase="another-passphrase",
        format="sql",
    )
    assert report["status"] == "exported"
    plain = tmp_path / "out.sql"
    decrypt_file(dest, plain, "another-passphrase")
    sql = plain.read_text(encoding="utf-8")
    assert "INSERT INTO" in sql and "ada" in sql and "s3cret-value" in sql

    refused = plugin.execute(
        _connection(db), table="people", dest=tmp_path / "nope.enc", passphrase=""
    )
    assert refused["status"] == "fail"
    assert not (tmp_path / "nope.enc").exists()


def test_viewer_cannot_export(tmp_path, isolated_secure_store, monkeypatch):
    store, _ = isolated_secure_store
    _auth(store, monkeypatch)
    import db_storage_manager.security.auth as auth_mod

    auth = auth_mod._auth_manager
    auth.bootstrap_admin("admin", "password123", email="admin@localhost")
    auth.authenticate("admin", "password123")
    auth.create_user(
        "viewer", "password123", email="view@example.com", role=UserRole.VIEWER
    )
    auth.logout()
    auth.authenticate("viewer", "password123")
    db = tmp_path / "people.db"
    _seed(db)
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    with pytest.raises(PermissionDenied):
        plugin.execute(
            _connection(db),
            table="people",
            dest=tmp_path / "x.enc",
            passphrase="correct horse battery",
        )


def test_parquet_without_an_engine_is_not_available(
    tmp_path, isolated_secure_store, monkeypatch
):
    store, _ = isolated_secure_store
    _auth(store, monkeypatch)
    db = tmp_path / "people.db"
    _seed(db)
    plugin = load_plugin_from_directory(PLUGIN_DIR)
    import importlib.util

    has_engine = any(
        importlib.util.find_spec(name) is not None
        for name in ("pyarrow", "fastparquet")
    )
    dest = tmp_path / "people.parquet.enc"
    report = plugin.execute(
        _connection(db),
        table="people",
        dest=dest,
        passphrase="correct horse battery",
        format="parquet",
    )
    if has_engine:
        assert report["status"] == "exported"
        assert dest.is_file()
    else:
        assert report["status"] == "not_available"
        assert not dest.exists()
