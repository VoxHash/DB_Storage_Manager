"""Restore and dry-run completion always paint the Backups status line."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from db_storage_manager import config  # noqa: E402
from db_storage_manager.backups.base import BackupInfo  # noqa: E402
from db_storage_manager.experimental import ENV_VAR  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.delenv(ENV_VAR, raising=False)
    return application


@pytest.fixture
def backups(app, tmp_path, monkeypatch, isolated_secure_store):
    from db_storage_manager.backups import scheduler as scheduler_mod
    from db_storage_manager.gui.backups import BackupsWidget

    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    monkeypatch.setattr(
        scheduler_mod, "SCHEDULED_BACKUPS_FILE", tmp_path / "schedules.json"
    )
    db = tmp_path / "lab.db"
    sqlite3.connect(str(db)).close()
    widget = BackupsWidget(
        [
            {
                "id": f"ui-{tmp_path.name}",
                "name": "lab-sqlite",
                "type": "sqlite",
                "database": str(db),
            }
        ],
        backup_dir=tmp_path / "bk",
    )
    widget.show()
    app.processEvents()
    yield widget
    widget.shutdown()
    widget.close()


def _select_backup(widget, tmp_path):
    path = tmp_path / "bk" / "sample.dump"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dump")
    info = BackupInfo(
        id="b-status",
        name="sample.dump",
        path=str(path),
        size=4,
        createdAt=datetime.now(),
        status="completed",
        metadata={"databaseType": "postgres"},
    )
    widget._backups = [info]
    widget._populate_table()
    widget.backups_table.selectRow(0)
    widget._set_status("Select a backup to verify checksum or run a restore dry-run.", "idle")
    return info


def _accept_dialogs(monkeypatch, *, scratch: bool = False):
    from db_storage_manager.gui import backups as backups_gui

    class _AutoDialog:
        DialogCode = backups_gui.RestoreDialog.DialogCode

        def __init__(self, backup, targets, **kwargs):
            self.targets = targets

        def exec(self):
            return backups_gui.RestoreDialog.DialogCode.Accepted

        def result_values(self):
            return {
                "target": self.targets[0],
                "confirmation": "lab.db",
                "passphrase": None,
                "safety_backup": False,
                "safety_passphrase": None,
                "scratch": scratch,
            }

    monkeypatch.setattr(backups_gui, "RestoreDialog", _AutoDialog)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def _run_restore(widget, monkeypatch, result, *, scratch: bool = False, raises: BaseException | None = None):
    _accept_dialogs(monkeypatch, scratch=scratch)

    async def fake(*_args, **_kwargs):
        if raises is not None:
            raise raises
        return result

    if scratch:
        widget.backup_manager.scratch_restore = fake
    else:
        widget.backup_manager.full_restore = fake
    widget.restore_selected()
    widget.wait_idle(10000)


def test_postgres_acl_success_stays_after_the_list_reloads(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)
    _run_restore(
        widget,
        monkeypatch,
        {
            "ok": True,
            "safetyBackup": "pre-restore.enc",
            "restoreNotice": "Skipped ACLs the session cannot apply.",
        },
    )
    text = widget.verify_status_label.text()
    assert "Restore finished" in text
    assert "pre-restore.enc" in text
    assert "Skipped ACLs" in text
    assert "Restoring backup" not in text
    assert "Loaded" not in text
    assert widget._jobs.any_busy() is False


def test_scratch_restore_keeps_the_acl_note(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)
    _run_restore(
        widget,
        monkeypatch,
        {
            "ok": True,
            "scratch": True,
            "scratchDatabase": "dsm_scratch_lab",
            "restoreNotice": "Skipped ACLs the session cannot apply.",
        },
        scratch=True,
    )
    text = widget.verify_status_label.text()
    assert "dsm_scratch_lab" in text
    assert "Production was not modified" in text
    assert "Skipped ACLs" in text
    assert "Restoring backup" not in text


def test_mariadb_client_failure_is_shown(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)
    _run_restore(
        widget,
        monkeypatch,
        None,
        raises=RuntimeError(
            "mariadb (/usr/bin/mariadb): libedit.so.2: cannot open shared object file"
        ),
    )
    text = widget.verify_status_label.text()
    assert text.startswith("Restore failed:")
    assert "libedit.so.2" in text
    assert "/usr/bin/mariadb" in text
    assert "Restoring backup" not in text
    assert "Loaded" not in text


def test_empty_restore_results_still_set_a_status(app, backups, monkeypatch, tmp_path):
    widget = backups

    def restore(result):
        # The post-restore refresh lists real files only, so reselect each time.
        _select_backup(widget, tmp_path)
        _run_restore(widget, monkeypatch, result)

    restore({"ok": True, "safetyBackup": None, "restoreNotice": "  "})
    assert widget.verify_status_label.text() == "Restore finished."

    restore(None)
    assert widget.verify_status_label.text() == "Restore finished."

    restore({"ok": False, "error": ""})
    text = widget.verify_status_label.text()
    assert text.startswith("Restore failed:")
    assert "unknown error" in text

    restore({"ok": False, "error": "mysql restore failed:"})
    assert "mysql restore failed:" in widget.verify_status_label.text()


def test_dry_run_success_failure_and_client_error(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)

    widget.backup_manager.dry_run_restore = lambda *a, **k: {"ok": True, "integrity": ""}
    widget.dry_run_selected()
    widget.wait_idle(10000)
    assert "PASS" in widget.verify_status_label.text()
    assert "dry-run" in widget.verify_status_label.text().lower()
    assert "in progress" not in widget.verify_status_label.text().lower()

    widget.backup_manager.dry_run_restore = lambda *a, **k: {
        "ok": False,
        "status": "fail",
        "stage": "",
        "error": "",
    }
    widget.dry_run_selected()
    widget.wait_idle(10000)
    failed = widget.verify_status_label.text()
    assert failed.startswith("FAIL")
    assert "dry-run" in failed.lower()
    assert "in progress" not in failed.lower()

    def boom(*_args, **_kwargs):
        raise RuntimeError(
            "mysql (/usr/bin/mysql): libedit.so.2: cannot open shared object file"
        )

    widget.backup_manager.dry_run_restore = boom
    widget.dry_run_selected()
    widget.wait_idle(10000)
    text = widget.verify_status_label.text()
    assert text.startswith("FAIL")
    assert "libedit.so.2" in text
    assert "Failed to refresh" not in text
    assert "in progress" not in text.lower()

    widget.backup_manager.dry_run_restore = lambda *a, **k: None
    widget.dry_run_selected()
    widget.wait_idle(10000)
    assert widget.verify_status_label.text().startswith("FAIL")
