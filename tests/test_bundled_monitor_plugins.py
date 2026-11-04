"""Connection email alerts and multi-connection health checks."""

from __future__ import annotations

import json
import sqlite3

from db_storage_manager.monitoring.alerts import Alert, AlertSeverity
from db_storage_manager.monitoring.connection_email import handle, reset_state
from db_storage_manager.monitoring.multi_watch import reset_state as reset_watch
from db_storage_manager.monitoring.multi_watch import watch
from db_storage_manager.monitoring.notifications import NotificationDispatcher
from db_storage_manager.plugins.sdk import CATALOG_PLUGIN_RULES
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
)
import db_storage_manager.plugins.sdk as sdk_mod
import db_storage_manager.security.auth as auth_mod
import pytest


PROFILE = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 2525,
    "security": "none",
    "username": "relay",
    "password": "smtp-secret-value",
    "sender": "dsm@example.com",
    "recipients": ["oncall@example.com"],
    "min_severity": "warning",
    "cooldown_minutes": 30,
}


def test_sdk_contract_matches_the_roadmap_note():
    text = sdk_mod.__doc__ or ""
    for phrase in CATALOG_PLUGIN_RULES:
        assert phrase in text


def test_connection_email_hides_the_password(isolated_secure_store):
    reset_state()
    sent = []

    def sender(cfg, message):
        sent.append((cfg["password"], message["To"]))

    saved = handle("conn-1", profile=PROFILE)
    assert saved["status"] == "saved"
    assert "smtp-secret-value" not in json.dumps(saved)
    from db_storage_manager.monitoring.connection_email import list_public_profiles

    public = list_public_profiles()
    assert public["conn-1"]["password_set"] is True
    assert "smtp-secret-value" not in json.dumps(public)
    alert = Alert("Disk", "full", AlertSeverity.CRITICAL, "storage", "conn-1")
    result = handle("conn-1", alert, sender=sender, clock=lambda: 0.0)
    assert result == {"status": "sent", "connection_id": "conn-1"}
    assert sent[0][0] == "smtp-secret-value"
    again = handle("conn-1", alert, sender=sender, clock=lambda: 10.0)
    assert again["status"] == "not_available"
    assert len(sent) == 1


def test_connection_email_is_off_until_enabled(isolated_secure_store):
    reset_state()
    handle("conn-1", profile={**PROFILE, "enabled": False})
    alert = Alert("Disk", "full", AlertSeverity.CRITICAL, "storage", "conn-1")
    result = handle("conn-1", alert, sender=lambda *a, **k: None, clock=lambda: 0.0)
    assert result["status"] == "not_available"


def test_dispatcher_sends_only_when_the_plugin_is_installed(
    marketplace, isolated_secure_store
):
    reset_state()
    mp, _store, _plugins = marketplace
    from db_storage_manager.bundled_plugins import bundled_plugin_dir

    mp.install_from_path(bundled_plugin_dir("connection-email-alerts"))
    handle("conn-9", profile=PROFILE)
    seen = []

    def sender(cfg, message):
        seen.append(cfg["password"])

    import db_storage_manager.monitoring.connection_email as email_mod

    original = email_mod.send_email
    email_mod.send_email = sender
    try:
        dispatcher = NotificationDispatcher(
            {"in_app": False, "desktop": False, "email": False},
            clock=lambda: 0.0,
        )
        alert = Alert("Disk", "full", AlertSeverity.WARNING, "storage", "conn-9")
        assert "connection_email" in dispatcher.notify(alert)
        assert dispatcher.wait_email_idle(5)
    finally:
        email_mod.send_email = original
    assert seen == ["smtp-secret-value"]
    blob = json.dumps(dispatcher.delivered)
    assert "smtp-secret-value" not in blob


def test_multi_watch_is_opt_in_rate_limited_and_omits_passwords(
    isolated_secure_store, tmp_path
):
    reset_watch()
    store, _data = isolated_secure_store
    database = tmp_path / "watched.db"
    sqlite3.connect(database).close()
    store.save_connections(
        [
            {
                "id": "c1",
                "name": "watched",
                "type": "sqlite",
                "database": str(database),
                "password": "db-secret-value",
            }
        ]
    )
    calls = []

    def poll(connection_id):
        calls.append(connection_id)
        return {"status": "healthy", "summary": "ok"}

    now = [0.0]
    first = watch(connection_ids=["c1"], poll=poll, clock=lambda: now[0])
    assert first["status"] == "ok"
    assert first["connections"] == [{"id": "c1", "status": "healthy", "summary": "ok"}]
    assert "db-secret-value" not in json.dumps(first)
    second = watch(poll=poll, clock=lambda: now[0])
    assert second["status"] == "not_available"
    assert second["reason"] == "Rate limited."
    assert calls == ["c1"]
    now[0] = 61.0
    third = watch(poll=poll, clock=lambda: now[0])
    assert third["status"] == "ok"
    assert calls == ["c1", "c1"]


def test_multi_watch_uses_the_health_checker(isolated_secure_store, tmp_path):
    reset_watch()
    store, _data = isolated_secure_store
    database = tmp_path / "live.db"
    sqlite3.connect(database).close()
    store.save_connections(
        [
            {
                "id": "c2",
                "name": "live",
                "type": "sqlite",
                "database": str(database),
                "password": "db-secret-value",
            }
        ]
    )
    report = watch(connection_ids=["c2"], clock=lambda: 0.0)
    assert report["connections"][0]["status"] in {
        "healthy",
        "degraded",
        "unhealthy",
        "unknown",
        "not_available",
    }
    assert "db-secret-value" not in json.dumps(report)


def test_monitor_role_cannot_save_the_watch_list(isolated_secure_store, monkeypatch):
    reset_watch()
    store, _data = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("mon", "password123", role=UserRole.MONITOR, email="m@x")
    auth.logout()
    auth.authenticate("mon", "password123")
    monkeypatch.setattr(auth_mod, "_auth_manager", auth)
    with pytest.raises(PermissionDenied):
        watch(connection_ids=["c1"], poll=lambda _cid: {"status": "healthy"})


def test_broken_email_plugin_does_not_block_other_channels(
    marketplace, isolated_secure_store
):
    reset_state()
    mp, _store, plugins_dir = marketplace
    from db_storage_manager.bundled_plugins import bundled_plugin_dir

    mp.install_from_path(bundled_plugin_dir("connection-email-alerts"))
    handle("conn-1", profile=PROFILE)
    broken = plugins_dir / "installed" / "connection-email-alerts" / "plugin.py"
    broken.write_text("raise RuntimeError('broken plugin')\n", encoding="utf-8")
    dispatcher = NotificationDispatcher(
        {"in_app": True, "desktop": False, "email": False},
        clock=lambda: 0.0,
    )
    alert = Alert("Disk", "full", AlertSeverity.CRITICAL, "storage", "conn-1")
    fired = dispatcher.notify(alert)
    assert "connection_email" not in fired
    assert dispatcher.in_app_log


def test_channels_tab_saves_email_and_polls_opted_in_connections(
    marketplace, isolated_secure_store, tmp_path, monkeypatch
):
    """The Plugins page Enable flag is not enough: Channels must save and run."""
    import os
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from db_storage_manager.bundled_plugins import bundled_plugin_dir
    from db_storage_manager.gui.monitoring import MonitoringWidget
    import db_storage_manager.monitoring.connection_email as email_mod

    reset_state()
    reset_watch()
    mp, store, _plugins = marketplace
    mp.install_from_path(bundled_plugin_dir("connection-email-alerts"))
    mp.install_from_path(bundled_plugin_dir("multi-connection-monitor"))
    database = tmp_path / "watched.db"
    sqlite3.connect(database).close()
    connection = {
        "id": "c-mail",
        "name": "watched",
        "type": "sqlite",
        "database": str(database),
        "password": "db-secret-value",
    }
    store.save_connections([connection])
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))

    app = QApplication.instance() or QApplication([])
    widget = MonitoringWidget([connection])
    try:
        assert widget.conn_email_save.isEnabled()
        assert widget.multi_save.isEnabled()
        widget.conn_email_enabled.setChecked(True)
        widget.conn_email_host.setText(PROFILE["host"])
        widget.conn_email_port.setValue(PROFILE["port"])
        widget.conn_email_security.setCurrentIndex(
            widget.conn_email_security.findData(PROFILE["security"])
        )
        widget.conn_email_user.setText(PROFILE["username"])
        widget.conn_email_password.setText(PROFILE["password"])
        widget.conn_email_sender.setText(PROFILE["sender"])
        widget.conn_email_recipients.setText(", ".join(PROFILE["recipients"]))
        widget.conn_email_severity.setCurrentIndex(
            widget.conn_email_severity.findData(PROFILE["min_severity"])
        )
        widget.conn_email_save.click()
        app.processEvents()
        assert "smtp-secret-value" not in widget.conn_email_status.text()
        assert widget.conn_email_password.text() == ""
        stored = store.get_settings()["connection_email_alerts"]["connections"]["c-mail"]
        assert stored["password"] == "smtp-secret-value"
        assert stored["enabled"] is True

        sent = []

        def sender(cfg, message):
            sent.append(cfg["password"])

        original = email_mod.send_email
        email_mod.send_email = sender
        try:
            alert = Alert("Disk", "full", AlertSeverity.WARNING, "storage", "c-mail")
            assert "connection_email" in widget.notification_dispatcher.notify(alert)
            assert widget.notification_dispatcher.wait_email_idle(5)
        finally:
            email_mod.send_email = original
        assert sent == ["smtp-secret-value"]
        assert "smtp-secret-value" not in json.dumps(
            widget.notification_dispatcher.delivered
        )

        assert widget.multi_list.count() == 1
        widget.multi_list.item(0).setCheckState(Qt.CheckState.Checked)
        widget.multi_save.click()
        deadline = time.monotonic() + 15
        while widget.multi_results.rowCount() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert widget.multi_results.rowCount() == 1
        shown = " ".join(
            widget.multi_results.item(0, col).text()
            for col in range(3)
            if widget.multi_results.item(0, col) is not None
        )
        assert "c-mail" in shown
        assert "db-secret-value" not in shown
        assert "db-secret-value" not in widget.multi_status.text()
        assert store.get_settings()["multi_connection_monitor"]["connection_ids"] == [
            "c-mail"
        ]
    finally:
        widget.shutdown()
        widget.close()
        app.processEvents()
