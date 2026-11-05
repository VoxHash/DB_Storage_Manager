"""Tabbed Settings, single sign-in indicator, theming, size explanation, restore UI."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QHeaderView,
    QMessageBox,
    QTabWidget,
)

from db_storage_manager import config  # noqa: E402
from db_storage_manager.experimental import ENV_VAR  # noqa: E402
from db_storage_manager.security.auth import (  # noqa: E402
    get_auth_manager,
    reset_auth_manager,
)
from db_storage_manager.security.bootstrap import bootstrap_admin  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    application = QApplication.instance() or QApplication([])
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.delenv(ENV_VAR, raising=False)
    return application


@pytest.fixture
def settings_widget(app, isolated_secure_store, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    from db_storage_manager.gui.settings import SettingsWidget

    widget = SettingsWidget()
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def _pump(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return predicate()


# ----------------------------------------------------------------- settings


def test_settings_is_tabbed_with_clean_labels(settings_widget):
    tabs = settings_widget.tabs
    assert tabs.count() == 5
    titles = [tabs.tabText(i) for i in range(5)]
    assert titles[0] == "General"
    # "&" is a mnemonic marker in Qt: it must be escaped to survive in the title.
    assert titles[1] == "Backups && Adapters"
    assert titles[2] == "Notifications"
    assert titles[3] == "Users && RBAC"
    assert titles[4] == "Updates"
    # No doubled colon ("Theme::") and exactly one colon per form label.
    for label in (
        settings_widget.theme_label,
        settings_widget.language_label,
        settings_widget.safe_mode_label,
        settings_widget.notifications_label,
    ):
        assert label.text().endswith(":") and not label.text().endswith("::")
    assert settings_widget.alerts_group.title() == "Alerts && monitoring"


def test_language_switch_retranslates_all_tabs_and_users_panel(settings_widget, app):
    idx = settings_widget.language_combo.findData("ru")
    settings_widget.language_combo.setCurrentIndex(idx)
    app.processEvents()
    assert settings_widget.tabs.tabText(0) == "Общие"
    assert settings_widget.tabs.tabText(4) == "Обновления"
    assert settings_widget.users_admin.group.title() == "Пользователи и RBAC"
    assert settings_widget.users_admin.add_btn.text() != "Add user…"
    assert settings_widget.theme_label.text().count(":") == 1
    assert settings_widget.save_button.text() != "Save Settings"


def test_save_button_is_hidden_on_the_users_tab(settings_widget):
    settings_widget.tabs.setCurrentIndex(0)
    assert settings_widget.save_button.isVisible()
    settings_widget.tabs.setCurrentIndex(1)
    assert settings_widget.save_button.isVisible()
    settings_widget.tabs.setCurrentIndex(3)
    assert not settings_widget.save_button.isVisible()
    settings_widget.tabs.setCurrentIndex(4)
    assert settings_widget.save_button.isVisible()
    assert settings_widget.updates_panel.check_button.text()


def test_save_merges_instead_of_dropping_other_tabs_settings(settings_widget, monkeypatch):
    store = settings_widget.secure_store
    stored = store.get_settings()
    stored["alert_channels"] = {"desktop": False, "in_app": True, "email": False}
    stored["s3_backup"] = {
        "bucket": "keep-me",
        "prefix": "p/",
        "region": "eu-west-1",
        "endpoint": "",
        "accessKeyId": "AKIDKEEP",
        "secretAccessKey": "keep-secret",
    }
    stored["custom_unknown_key"] = {"x": 1}
    stored["window"] = {"width": 1280, "height": 900}
    store.set_settings(stored)

    w = settings_widget
    w.safe_mode_check.setChecked(False)
    w.experimental_restore_check.setChecked(True)
    w.email_host_edit.setText("smtp.example.com")
    w.email_port_spin.setValue(465)
    w.email_security_combo.setCurrentIndex(w.email_security_combo.findData("ssl"))
    w.email_user_edit.setText("alerts")
    w.email_password_edit.setText("smtp-password-123")
    w.email_sender_edit.setText("dsm@example.com")
    w.email_recipients_edit.setText("a@example.com; b@example.com")
    w.email_severity_combo.setCurrentIndex(w.email_severity_combo.findData("warning"))
    w.email_cooldown_spin.setValue(45)
    w._save_settings()

    saved = store.get_settings()
    assert saved["safe_mode"] is False
    assert saved["experimental"]["restore"] is True
    assert saved["alert_channels"]["desktop"] is False
    assert saved["s3_backup"]["bucket"] == "keep-me"
    assert saved["s3_backup"]["secretAccessKey"] == "keep-secret"
    assert saved["window"] == {"width": 1280, "height": 900}
    assert saved["custom_unknown_key"] == {"x": 1}
    email = saved["email_alerts"]
    assert email["host"] == "smtp.example.com" and email["port"] == 465
    assert email["security"] == "ssl" and email["min_severity"] == "warning"
    assert email["recipients"] == ["a@example.com", "b@example.com"]
    assert email["cooldown_minutes"] == 45
    assert email["password"] == "smtp-password-123"
    assert w.email_password_edit.text() == ""  # never echoed back into the form

    # A second save with a blank password field keeps the stored one.
    w._save_settings()
    assert store.get_settings()["email_alerts"]["password"] == "smtp-password-123"

    # Secrets are encrypted on disk.
    import db_storage_manager.security.store as store_mod

    raw = store_mod.SETTINGS_FILE.read_bytes()
    assert b"smtp-password-123" not in raw and b"keep-secret" not in raw


def test_experimental_toggle_is_locked_when_env_forces_it(app, isolated_secure_store, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    from db_storage_manager.gui.settings import SettingsWidget

    widget = SettingsWidget()
    assert widget.experimental_restore_check.isChecked()
    assert not widget.experimental_restore_check.isEnabled()
    assert ENV_VAR in widget.experimental_hint.text()
    widget.close()


def test_adapter_table_lists_every_destination_honestly(settings_widget):
    table = settings_widget.adapters_table
    names = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert names == ["Local", "Proton Drive", "S3-compatible", "Google Drive"]
    assert table.item(0, 1).text() == "Ready"
    assert table.item(2, 1).text() == "Not configured"
    assert table.item(3, 1).text() == "API only"
    # Header carries no stray colon from the form-label translation.
    assert table.horizontalHeaderItem(0).text() == "Adapter"


def test_users_panel_inherits_the_active_theme(settings_widget, app):
    """The RBAC panel must not freeze the stylesheet of the theme it was built under."""
    from db_storage_manager.themes.manager import get_theme_manager

    assert settings_widget.users_admin.styleSheet() == ""
    manager = get_theme_manager()
    original = manager.current_theme
    try:
        for theme in ("light", "dark", "dracula"):
            manager.set_theme(theme)
            from db_storage_manager.gui.utils import apply_glassmorphism

            apply_glassmorphism(settings_widget)
            app.processEvents()
            assert settings_widget.users_admin.styleSheet() == ""
            colors = manager.get_theme()["colors"]
            assert colors["surface_elevated"].lower() in settings_widget.styleSheet().lower()
    finally:
        manager.set_theme(original)


# ----------------------------------------------------- shell / plugins / size


def test_builtin_plugins_are_authored_by_voxhash(app, isolated_secure_store, tmp_path, monkeypatch):
    import db_storage_manager.config as config_mod
    from db_storage_manager.plugins.marketplace import LocalPluginMarketplace

    plugins_dir = isolated_secure_store[1] / "plugins"
    plugins_dir.mkdir()
    monkeypatch.setattr(config_mod, "PLUGINS_DIR", plugins_dir)
    marketplace = LocalPluginMarketplace(plugins_dir=plugins_dir)
    marketplace.sync_builtins()
    rows = {r["id"]: r for r in marketplace.list_installed()}
    assert rows["data_comparison"]["author"] == "VoxHash"
    assert rows["migration"]["author"] == "VoxHash"


def test_main_window_has_one_signed_in_indicator(app, isolated_secure_store, tmp_path, monkeypatch):
    store, _ = isolated_secure_store
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    reset_auth_manager()
    bootstrap_admin("admin", "password123", store=store)
    auth = get_auth_manager()
    auth.reload()
    assert auth.authenticate("admin", "password123") is not None

    from db_storage_manager.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    assert "admin" in window.sidebar.footer.text()
    assert not window.statusBar().isVisible()
    assert window.statusBar().currentMessage() == ""
    window.close()
    reset_auth_manager()


# --------------------------------------------------------------- backups UI


@pytest.fixture
def backups(app, tmp_path, monkeypatch, isolated_secure_store):
    from db_storage_manager.backups import scheduler as scheduler_mod
    from db_storage_manager.gui.backups import BackupsWidget

    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    monkeypatch.setattr(
        scheduler_mod, "SCHEDULED_BACKUPS_FILE", tmp_path / "schedules.json"
    )
    db = tmp_path / "lab.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO items(name) VALUES (?)", [("x" * 300,) for _ in range(400)]
    )
    conn.commit()
    conn.close()
    connections = [
        {
            "id": f"ui-{tmp_path.name}",
            "name": "lab-sqlite",
            "type": "sqlite",
            "database": str(db),
        }
    ]
    widget = BackupsWidget(connections, backup_dir=tmp_path / "bk")
    widget.show()
    yield widget, db, tmp_path
    widget.shutdown()
    widget.close()


def _create_backup(app, widget, **kwargs):
    compression = kwargs.get("compression", "gzip")
    widget.compression_combo.setCurrentIndex(
        widget.compression_combo.findData(compression)
    )
    widget.encrypt_checkbox.setChecked(False)
    widget.create_backup()
    widget.wait_idle(20000)
    widget.refresh_backups()
    widget.wait_idle(20000)
    app.processEvents()


def test_backup_table_explains_stored_vs_live_size(app, backups):
    widget, db, _ = backups
    _create_backup(app, widget)
    assert widget.backups_table.rowCount() == 1
    stored = widget.backups_table.item(0, 1).text()
    source = widget.backups_table.item(0, 2).text()
    assert source != "—"
    assert stored != source
    backup = widget._selected_backup() or widget._backups[0]
    assert backup.size < backup.metadata["dumpSize"]
    assert backup.metadata["sourceStorageBytes"] >= backup.metadata["dumpSize"] // 2
    tip = widget.backups_table.item(0, 1).toolTip()
    assert "Stored file" in tip and "Live database" in tip and "Dump before" in tip
    assert "logical data" in tip
    assert widget.size_explainer_label.text().startswith("Size is the stored file")
    assert widget.size_explainer_label.wordWrap()


def test_restore_explainer_clears_the_table_and_keeps_created(app, backups):
    """The size sentence stays above the grid, and Created is the local timestamp."""
    from datetime import datetime

    from db_storage_manager.backups.base import BackupInfo

    widget, _, _ = backups
    long_name = "asesoresyasociados.org_e5d275db_20261105_013014.backup.zst.enc"
    created = datetime(2026, 11, 5, 1, 30, 14)
    widget._backups = [
        BackupInfo(
            id="row-1",
            name=long_name,
            path="/tmp/row-1",
            size=258007,
            createdAt=created,
            status="completed",
            metadata={},
        )
    ]
    widget._populate_table()

    widget.resize(780, 720)
    label = widget.size_explainer_label
    table = widget.backups_table
    tabs = widget.findChild(QTabWidget)
    assert tabs is not None
    tabs.setCurrentWidget(label.parentWidget())
    label.parentWidget().layout().activate()
    app.processEvents()

    assert label.wordWrap()
    assert label.hasHeightForWidth()
    assert label.height() >= label.heightForWidth(label.width()) - 2
    assert label.geometry().bottom() <= table.geometry().top()

    narrow = label.height()
    widget.resize(1400, 720)
    label.parentWidget().layout().activate()
    app.processEvents()
    assert label.geometry().bottom() <= table.geometry().top()
    assert narrow >= label.height()

    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(3) == QHeaderView.ResizeMode.ResizeToContents
    assert table.textElideMode() == Qt.TextElideMode.ElideMiddle
    name_item = table.item(0, 0)
    assert name_item.text() == long_name
    assert name_item.toolTip() == long_name
    assert table.item(0, 3).text() == "2026-11-05 01:30:14"
    assert table.item(0, 5).text() == "UNKNOWN"
    assert table.item(0, 6).text() == "Not verified"


def test_off_machine_adapters_force_encryption(app, backups):
    widget, _, _ = backups
    assert [widget.adapter_combo.itemData(i) for i in range(widget.adapter_combo.count())] == [
        "local",
        "protondrive",
        "s3",
    ]
    widget.adapter_combo.setCurrentIndex(widget.adapter_combo.findData("s3"))
    assert widget.encrypt_checkbox.isChecked()
    assert not widget.encrypt_checkbox.isEnabled()
    assert not widget.configure_s3_button.isHidden()
    assert widget.configure_proton_button.isHidden()
    widget.adapter_combo.setCurrentIndex(widget.adapter_combo.findData("local"))
    assert widget.encrypt_checkbox.isEnabled()


def test_restore_button_is_visible_by_default_and_hides_when_turned_off(app, backups):
    widget, _, _ = backups
    widget.refresh_destinations()
    assert not widget.restore_button.isHidden()
    assert widget.restore_button.isEnabled()

    from db_storage_manager.security.store import SecureStore

    settings = SecureStore()
    data = settings.get_settings()
    data["experimental"] = {"restore": False}
    settings.set_settings(data)
    widget.refresh_destinations()
    assert widget.restore_button.isHidden()


def test_restore_dialog_requires_typed_name_and_passphrases(app, backups, monkeypatch):
    from db_storage_manager.gui.restore_dialog import RestoreDialog

    widget, db, _ = backups
    monkeypatch.setenv(ENV_VAR, "1")
    _create_backup(app, widget)
    backup = widget._backups[0]
    targets = widget._restore_targets()
    assert targets and targets[0].database == str(db)

    dialog = RestoreDialog(backup, targets)
    assert dialog.required_phrase() == "lab.db"
    assert not dialog.ok_button.isEnabled()
    dialog.confirm_edit.setText("lab.db")
    assert not dialog.ok_button.isEnabled()  # safety backup passphrase still missing
    dialog.safety_passphrase_edit.setText("safety-pass")
    assert dialog.ok_button.isEnabled()
    dialog.confirm_edit.setText("other.db")
    assert not dialog.ok_button.isEnabled()
    dialog.confirm_edit.setText("lab.db")
    dialog.safety_check.setChecked(False)
    dialog.safety_passphrase_edit.clear()
    assert dialog.ok_button.isEnabled()
    values = dialog.result_values()
    assert values["safety_backup"] is False and values["safety_passphrase"] is None


def test_restore_button_runs_a_real_restore_after_both_confirmations(app, backups, monkeypatch):
    from db_storage_manager.gui import backups as backups_gui

    widget, db, tmp = backups
    monkeypatch.setenv(ENV_VAR, "1")
    _create_backup(app, widget)
    widget.backups_table.selectRow(0)

    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM items")
    conn.commit()
    conn.close()

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
                "safety_backup": True,
                "safety_passphrase": "safety-pass",
            }

    monkeypatch.setattr(backups_gui, "RestoreDialog", _AutoDialog)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    widget.restore_selected()
    assert _pump(app, lambda: not widget._jobs.any_busy(), 20)
    widget.wait_idle(20000)

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 400
    conn.close()
    # The safety backup is listed next to the original after the post-restore refresh.
    assert widget.backups_table.rowCount() == 2
    assert any(p.suffix == ".enc" or ".enc" in p.name for p in (tmp / "bk").iterdir())
    from db_storage_manager.audit import read_audit

    assert read_audit()[-1]["outcome"] == "completed"


def test_restore_is_refused_in_the_ui_while_turned_off(app, backups):
    widget, db, _ = backups
    from db_storage_manager.security.store import SecureStore

    settings = SecureStore()
    data = settings.get_settings()
    data["experimental"] = {"restore": False}
    settings.set_settings(data)
    widget.refresh_destinations()
    _create_backup(app, widget)
    widget.backups_table.selectRow(0)
    widget.restore_selected()
    assert "turned off" in widget.verify_status_label.text().lower()
    assert widget._jobs.any_busy() is False


# -------------------------------------------------------------- dashboard


def test_dashboard_total_size_card_explains_itself(app, isolated_secure_store):
    from db_storage_manager.gui.dashboard import DashboardWidget

    dash = DashboardWidget([])
    tip = dash._metric_cards["total_size"].toolTip()
    assert "indexes" in tip and "backup" in tip.lower()
    dash.close()


# ------------------------------------------------------------- monitoring


def test_email_channel_needs_complete_smtp_and_autostart_watches(
    app, isolated_secure_store, tmp_path, monkeypatch
):
    store, _ = isolated_secure_store
    db = tmp_path / "watched.db"
    sqlite3.connect(str(db)).close()
    conn_id = f"mon-{tmp_path.name}"
    connection = {"id": conn_id, "name": "watched", "type": "sqlite", "database": str(db)}

    from db_storage_manager.gui.monitoring import MonitoringWidget

    widget = MonitoringWidget([connection])
    widget.update_connections([connection])
    assert not widget.email_channel_check.isEnabled()
    assert "Settings" in widget.email_channel_check.toolTip()

    settings = store.get_settings()
    settings["email_alerts"] = {
        **settings["email_alerts"],
        "host": "localhost",
        "security": "none",
        "sender": "dsm@example.com",
        "recipients": ["ops@example.com"],
    }
    settings["monitoring"] = {"autostart_connection_id": conn_id}
    store.set_settings(settings)
    widget.refresh_email_channel()
    assert widget.email_channel_check.isEnabled()

    widget.email_channel_check.setChecked(True)
    widget._save_channels()
    assert store.get_settings()["alert_channels"]["email"] is True
    assert widget.notification_dispatcher.channels["email"] is True

    assert widget.autostart_if_configured() is True
    assert _pump(app, lambda: widget.monitor is not None, 10)
    assert widget.current_connection["id"] == conn_id
    widget._stop_monitoring()
    widget.shutdown()
    widget.close()


def test_local_backup_directory_is_saved_and_used(settings_widget, tmp_path, monkeypatch):
    from db_storage_manager.backups import scheduler as scheduler_mod
    from db_storage_manager.backups.local import resolve_local_backup_dir
    from db_storage_manager.gui.backups import BackupsWidget

    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit-dir.log")
    monkeypatch.setattr(
        scheduler_mod, "SCHEDULED_BACKUPS_FILE", tmp_path / "schedules.json"
    )
    custom = tmp_path / "custom-backups"
    custom.mkdir()
    settings_widget.local_backup_dir_edit.setText(str(custom))
    settings_widget._save_settings()
    assert settings_widget.secure_store.get_settings()["local_backup_dir"] == str(custom)

    widget = BackupsWidget([])
    try:
        assert Path(widget.backup_dir) == custom
        (custom / "keep.backup").write_bytes(b"archive")
        widget.refresh_backups()
        widget.wait_idle()
        assert any(item.name == "keep.backup" for item in widget._backups)
    finally:
        widget.shutdown()
        widget.close()

    settings_widget.local_backup_dir_edit.setText("/no/such/dsm-backup-dir")
    settings_widget._save_settings()
    assert settings_widget.secure_store.get_settings()["local_backup_dir"] == str(custom)

    settings_widget.local_backup_dir_edit.setText("")
    settings_widget._save_settings()
    assert settings_widget.secure_store.get_settings()["local_backup_dir"] == ""
    assert resolve_local_backup_dir() == config.BACKUP_DIR


def test_delete_removes_local_backup_after_confirmation(app, backups, monkeypatch):
    from PyQt6.QtCore import Qt

    widget, _db, tmp_path = backups
    _create_backup(app, widget)
    assert widget.backups_table.rowCount() == 1
    widget.backups_table.selectRow(0)
    backup = widget._backups[0]
    path = Path(backup.path)
    sidecar = Path(str(path) + ".meta.json")
    checksum = Path(str(path) + ".sha256")
    checksum.write_text("abc", encoding="utf-8")
    assert path.is_file() and sidecar.is_file()
    assert (
        widget.backups_table.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    widget.delete_selected()
    widget.wait_idle()
    assert not path.exists()
    assert not sidecar.exists()
    assert not checksum.exists()
    assert widget.backups_table.rowCount() == 0
    assert "backup.delete" in (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_delete_cancel_keeps_the_file(app, backups):
    widget, _db, _tmp = backups
    _create_backup(app, widget)
    path = Path(widget._backups[0].path)
    widget.backups_table.selectRow(0)
    widget.delete_selected()
    widget.wait_idle()
    assert path.is_file()
    assert widget.backups_table.rowCount() == 1


def test_delete_cloud_backup_uses_the_adapter(app, backups, monkeypatch):
    from datetime import datetime, timezone

    from db_storage_manager.backups.base import BackupInfo

    widget, _db, _tmp = backups
    deleted = []

    class Adapter:
        async def delete_backup(self, backup_id):
            deleted.append(backup_id)

        async def list_backups(self):
            return []

    backup = BackupInfo(
        id="cloud-1",
        name="lab.backup.enc",
        path="protondrive:DB-Storage-Manager/lab.backup.enc",
        size=10,
        createdAt=datetime.now(timezone.utc),
        status="completed",
        metadata={"destination": "protondrive"},
    )
    widget._list_source = "protondrive"
    widget._backups = [backup]
    widget._populate_table()
    widget.backups_table.selectRow(0)
    monkeypatch.setattr(widget.backup_manager, "get_adapter", lambda *a, **k: Adapter())
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    widget.delete_selected()
    widget.wait_idle()
    assert deleted == ["cloud-1"]
    assert widget.backups_table.rowCount() == 0


def test_delete_requires_backups_create(app, backups, isolated_secure_store):
    from db_storage_manager.security.auth import (
        AuthenticationManager,
        UserRole,
        reset_auth_manager,
    )
    from db_storage_manager.security import auth as auth_mod

    widget, _db, _tmp = backups
    _create_backup(app, widget)
    path = Path(widget._backups[0].path)
    store, _data = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("viewer1", "password123", role=UserRole.VIEWER)
    auth.logout()
    auth.authenticate("viewer1", "password123")
    auth_mod._auth_manager = auth
    try:
        widget.apply_rbac()
        assert widget.delete_button.isEnabled() is False
        widget.backups_table.selectRow(0)
        widget.delete_selected()
        widget.wait_idle()
        assert path.is_file()
    finally:
        reset_auth_manager()
