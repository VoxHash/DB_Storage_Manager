"""Backup checksum verification and restore dry-run (real files, no mocks)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from db_storage_manager.backups.base import BackupInfo, BackupOptions
from db_storage_manager.backups.local import LocalBackupAdapter, meta_path_for
from db_storage_manager.backups.manager import BackupManager
from db_storage_manager.native import sha256_file


def _sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items(name) VALUES ('alpha'), ('beta')")
        conn.commit()
    finally:
        conn.close()


def _backup_info(
    path: Path,
    *,
    sha256: str | None = None,
    compression: str = "none",
    database_type: str = "sqlite",
    backup_id: str = "b1",
) -> BackupInfo:
    metadata = {
        "compression": compression,
        "encryption": False,
        "databaseType": database_type,
    }
    if sha256 is not None:
        metadata["sha256"] = sha256
    return BackupInfo(
        id=backup_id,
        name=path.name,
        path=str(path),
        size=path.stat().st_size if path.exists() else 0,
        createdAt=datetime.now(),
        status="completed",
        metadata=metadata,
    )


@pytest.fixture
def local_adapter(tmp_path: Path) -> LocalBackupAdapter:
    return LocalBackupAdapter(base_path=tmp_path / "backups")


def test_local_create_persists_sha256_sidecar(local_adapter: LocalBackupAdapter, tmp_path: Path):
    source = tmp_path / "source.db"
    _sqlite_db(source)

    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="demo",
                databaseType="sqlite",
                backupPath=str(source),
                compression=None,
            )
        )
    )

    assert info.metadata.get("sha256")
    assert info.metadata["sha256"] == sha256_file(info.path)
    sidecar = meta_path_for(Path(info.path))
    assert sidecar.exists()

    listed = asyncio.run(local_adapter.list_backups())
    assert len(listed) == 1
    assert listed[0].metadata.get("sha256") == info.metadata["sha256"]
    assert listed[0].id == info.id


def test_verify_backup_checksum_pass_fail_missing(tmp_path: Path):
    manager = BackupManager()
    path = tmp_path / "ok.backup"
    path.write_bytes(b"payload-data\n" * 20)
    digest = sha256_file(path)

    passed = manager.verify_backup_checksum(_backup_info(path, sha256=digest))
    assert passed["ok"] is True
    assert passed["status"] == "pass"
    assert passed["actual"] == digest

    failed = manager.verify_backup_checksum(
        _backup_info(path, sha256="0" * 64, backup_id="b2")
    )
    assert failed["ok"] is False
    assert failed["status"] == "fail"
    assert failed["error"] == "SHA-256 mismatch"

    missing = manager.verify_backup_checksum(_backup_info(path, sha256=None, backup_id="b3"))
    assert missing["ok"] is False
    assert missing["status"] == "missing_checksum"

    gone = manager.verify_backup_checksum(
        _backup_info(tmp_path / "missing.backup", sha256=digest, backup_id="b4")
    )
    assert gone["ok"] is False
    assert gone["status"] == "not_found"


def test_verify_backups_parallel(tmp_path: Path):
    manager = BackupManager()
    paths = []
    infos = []
    for index in range(3):
        path = tmp_path / f"batch-{index}.backup"
        path.write_bytes(f"batch-{index}\n".encode() * 50)
        paths.append(path)
        infos.append(
            _backup_info(
                path,
                sha256=sha256_file(path),
                backup_id=f"p{index}",
            )
        )

    # Corrupt expected hash on the middle file
    infos[1].metadata["sha256"] = "f" * 64
    results = manager.verify_backups_parallel(infos)
    assert len(results) == 3
    assert results[0]["ok"] is True and results[0]["status"] == "pass"
    assert results[1]["ok"] is False and results[1]["status"] == "fail"
    assert results[2]["ok"] is True and results[2]["status"] == "pass"


def test_dry_run_restore_sqlite_pass(tmp_path: Path, local_adapter: LocalBackupAdapter):
    source = tmp_path / "live.db"
    _sqlite_db(source)
    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="sqlite-live",
                databaseType="sqlite",
                backupPath=str(source),
            )
        )
    )

    manager = BackupManager()
    result = manager.dry_run_restore(info)
    assert result["ok"] is True
    assert result["status"] == "pass"
    assert result["stage"] == "complete"
    assert result["integrity"] == "ok"
    assert result["checksum"]["ok"] is True
    # Live DB untouched
    assert source.exists()
    conn = sqlite3.connect(str(source))
    try:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_dry_run_restore_gzip_sqlite(tmp_path: Path, local_adapter: LocalBackupAdapter):
    source = tmp_path / "gz.db"
    _sqlite_db(source)
    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="sqlite-gz",
                databaseType="sqlite",
                backupPath=str(source),
                compression="gzip",
            )
        )
    )
    assert Path(info.path).suffix == ".gz"
    assert info.metadata.get("compression") == "gzip"

    manager = BackupManager()
    result = manager.dry_run_restore(info)
    assert result["ok"] is True
    assert result["integrity"] == "ok"


def test_dry_run_restore_fails_on_checksum_mismatch(tmp_path: Path):
    path = tmp_path / "bad.backup"
    _sqlite_db(path)
    info = _backup_info(path, sha256="a" * 64)
    result = BackupManager().dry_run_restore(info)
    assert result["ok"] is False
    assert result["stage"] == "checksum"
    assert result["status"] == "fail"


def test_dry_run_restore_fails_corrupt_sqlite_payload(tmp_path: Path):
    path = tmp_path / "corrupt.backup"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    info = _backup_info(path, sha256=digest)
    result = BackupManager().dry_run_restore(info)
    assert result["ok"] is False
    assert result["stage"] in {"integrity_check", "dry_run", "header"}


def test_delete_removes_sidecar(local_adapter: LocalBackupAdapter, tmp_path: Path):
    source = tmp_path / "del.db"
    _sqlite_db(source)
    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="to-delete",
                databaseType="sqlite",
                backupPath=str(source),
            )
        )
    )
    sidecar = meta_path_for(Path(info.path))
    assert Path(info.path).exists()
    assert sidecar.exists()
    asyncio.run(local_adapter.delete_backup(info.id))
    assert not Path(info.path).exists()
    assert not sidecar.exists()


def test_backups_widget_offscreen_smoke(tmp_path: Path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from db_storage_manager.gui.backups import BackupsWidget

    app = QApplication.instance() or QApplication([])
    backup_dir = tmp_path / "ui-backups"
    adapter = LocalBackupAdapter(base_path=backup_dir)
    source = tmp_path / "ui.db"
    _sqlite_db(source)
    info = asyncio.run(
        adapter.create_backup(
            BackupOptions(
                connectionId="ui-1",
                connectionName="ui-sqlite",
                databaseType="sqlite",
                backupPath=str(source),
            )
        )
    )

    widget = BackupsWidget([], backup_dir=backup_dir)
    assert widget.backups_table.columnCount() == 6
    assert widget.backups_table.rowCount() == 1
    assert widget.verify_selected_button.text()
    assert widget.dry_run_button.text()

    widget.backups_table.selectRow(0)
    widget.verify_selected()
    assert widget._verify_results[info.id]["ok"] is True
    assert "PASS" in widget.verify_status_label.text()

    widget.verify_all()
    assert "PASS" in widget.verify_status_label.text()

    widget.backups_table.selectRow(0)
    widget.dry_run_selected()
    dry = widget._verify_results[info.id]
    assert dry["ok"] is True
    assert dry.get("integrity") == "ok"
    assert dry.get("stage") == "complete"
    assert "PASS" in widget.verify_status_label.text()

    # Dry-run must not mutate the live source DB
    conn = sqlite3.connect(str(source))
    try:
        live_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()
    assert live_count == 2

    # Tamper file → checksum fail presentation
    Path(info.path).write_bytes(Path(info.path).read_bytes() + b"x")
    widget.refresh_backups()
    widget.backups_table.selectRow(0)
    widget.verify_selected()
    assert widget._verify_results[info.id]["ok"] is False
    assert "FAIL" in widget.verify_status_label.text()

    widget.update_connections([])
    widget.close()
    app.processEvents()
