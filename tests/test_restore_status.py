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


def test_restore_outcome_stays_on_the_row_after_reload(app, backups, monkeypatch, tmp_path):
    widget = backups
    path = tmp_path / "bk" / "sample.backup"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"plain-dump")
    meta = {
        "id": "b-status",
        "name": path.name,
        "compression": "none",
        "encryption": False,
        "databaseType": "postgres",
    }
    (tmp_path / "bk" / (path.name + ".meta.json")).write_text(
        __import__("json").dumps(meta),
        encoding="utf-8",
    )
    info = BackupInfo(
        id="b-status",
        name=path.name,
        path=str(path),
        size=path.stat().st_size,
        createdAt=datetime.now(),
        status="completed",
        metadata={"databaseType": "postgres"},
    )
    widget._backups = [info]
    widget._populate_table()
    widget.backups_table.selectRow(0)
    _run_restore(
        widget,
        monkeypatch,
        {"ok": True, "safetyBackup": None},
    )
    widget.wait_idle(10000)
    assert widget.backups_table.rowCount() >= 1
    status = widget.backups_table.item(0, 5).text()
    detail = widget.backups_table.item(0, 6).text()
    assert status == "PASS"
    assert detail == "Restored"
    assert widget.verify_status_label.text().startswith("Restore finished")
    assert "UNKNOWN" not in status


def test_row_shows_restoring_before_the_job_finishes(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)
    started = {}

    async def hold(*_args, **_kwargs):
        started["yes"] = True
        while not started.get("release"):
            await __import__("asyncio").sleep(0.01)
        return {"ok": True}

    _accept_dialogs(monkeypatch)
    widget.backup_manager.full_restore = hold
    widget.restore_selected()
    for _ in range(100):
        app.processEvents()
        if started.get("yes"):
            break
        __import__("time").sleep(0.01)
    assert widget.backups_table.item(0, 5).text() == "Restoring…"
    started["release"] = True
    widget.wait_idle(10000)
    assert widget._row_outcomes["b-status"]["status"] == "PASS"


def test_multi_select_menu_names_the_batch(app, backups):
    widget = backups
    entries = widget.context_menu_entries(3)
    labels = {kind: label for kind, label, _enabled in entries}
    assert "Verify 3 backups" in labels["verify"]
    assert "verify_all" not in labels
    assert "Dry-run 3 backups" in labels["dry_run"]
    assert "Restore 3 backups" in labels["restore"]
    assert "Delete 3 backups" in labels["delete"]
    single = [kind for kind, _label, _enabled in widget.context_menu_entries(1)]
    assert single == ["verify", "dry_run", "restore", "delete"]
    assert widget.verify_all_button.text() == widget.i18n.translate("backups.verify_all")
    assert widget.verify_all_button.isEnabled() == widget.menu_action_enabled("verify_all")


def test_two_restores_use_separate_workers(app, backups, monkeypatch, tmp_path):
    widget = backups
    infos = []
    for index in (1, 2):
        path = tmp_path / "bk" / f"sample-{index}.backup"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"dump")
        infos.append(
            BackupInfo(
                id=f"b-{index}",
                name=path.name,
                path=str(path),
                size=4,
                createdAt=datetime.now(),
                status="completed",
                metadata={"databaseType": "postgres"},
            )
        )
    widget._backups = infos
    widget._populate_table()
    from PyQt6.QtCore import QItemSelectionModel

    widget.backups_table.selectRow(0)
    widget.backups_table.selectionModel().select(
        widget.backups_table.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert len(widget._selected_backups()) == 2

    groups = []
    real_submit = widget._jobs.submit

    def spy(group, job, on_ok, on_fail=None, **kwargs):
        groups.append(group)
        return real_submit(group, job, on_ok, on_fail, **kwargs)

    monkeypatch.setattr(widget._jobs, "submit", spy)
    from db_storage_manager.gui.restore_dialog import RestoreBatchDialog

    class _Auto:
        DialogCode = RestoreBatchDialog.DialogCode

        def __init__(self, backups_in, targets, **kwargs):
            self.targets = targets

        def exec(self):
            return self.DialogCode.Accepted

        def result_values(self):
            return {
                "target": self.targets[0],
                "confirmation": "lab.db",
                "safety_backup": False,
                "safety_passphrase": None,
                "scratch": False,
                "passphrases": {},
            }

    monkeypatch.setattr(
        "db_storage_manager.gui.backups.RestoreBatchDialog", _Auto
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    seen = []

    async def fake(adapter, backup, target, **kwargs):
        seen.append(backup.id)
        return {"ok": True}

    widget.backup_manager.full_restore = fake
    widget.restore_selected()
    widget.wait_idle(10000)
    assert seen == ["b-1", "b-2"] or set(seen) == {"b-1", "b-2"}
    assert "restore:b-1" in groups
    assert "restore:b-2" in groups
    assert widget._row_outcomes["b-1"]["detail"] == "Restored"
    assert widget._row_outcomes["b-2"]["detail"] == "Restored"


def test_dry_run_uses_the_passphrase_that_opened_the_backup(app, backups, monkeypatch, tmp_path):
    widget = backups
    _select_backup(widget, tmp_path)
    info = widget._backups[0]
    info.metadata["encryption"] = True
    widget._populate_table()
    widget.backups_table.selectRow(0)
    widget._session_passphrases[info.id] = "right-key"
    widget.encryption_key_edit.setText("wrong-key")
    seen = []

    def fake(*_args, **kwargs):
        seen.append(kwargs.get("encryption_key"))
        return {"ok": True, "status": "pass", "stage": "complete", "integrity": ""}

    widget.backup_manager.dry_run_restore = fake
    widget.dry_run_selected()
    widget.wait_idle(10000)
    assert seen == ["right-key"]
    assert widget.backups_table.item(0, 5).text() == "PASS"
    assert widget.backups_table.item(0, 6).text() == "Dry-run OK"
