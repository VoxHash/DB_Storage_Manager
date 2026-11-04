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
