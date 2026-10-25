"""Tests for monitoring alerts and GUI presentation wiring."""

from __future__ import annotations

import asyncio
import copy
import os
from pathlib import Path

import pytest

from db_storage_manager.config import DEFAULT_ALERT_CHANNELS, DEFAULT_ALERT_THRESHOLDS
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.factory import DatabaseConnectionFactory
from db_storage_manager.monitoring import (
    Alert,
    AlertManager,
    AlertSeverity,
    DatabaseMonitor,
    NotificationDispatcher,
)


@pytest.fixture
def sqlite_db(tmp_path: Path):
    db_path = tmp_path / "monitor.db"
    cfg = ConnectionConfig(
        id="mon-1",
        name="monitor-sqlite",
        type="sqlite",
        database=str(db_path),
    )
    conn = DatabaseConnectionFactory.create_connection(cfg)
    asyncio.run(conn.connect())
    yield conn
    asyncio.run(conn.disconnect())


def test_alert_manager_thresholds_and_dedupe():
    manager = AlertManager()
    first = manager.check_metrics({"activeConnections": 60, "cacheHitRatio": 70})
    assert len(first) == 2
    assert {a.severity for a in first} == {
        AlertSeverity.WARNING,
        AlertSeverity.WARNING,
    }

    # Same thresholds again should not spam duplicate active alerts
    second = manager.check_metrics({"activeConnections": 60, "cacheHitRatio": 70})
    assert second == []
    assert manager.get_counts()["warning"] == 2
    assert manager.get_counts()["total"] == 2


def test_alert_manager_critical_and_acknowledge_by_id():
    manager = AlertManager()
    created = manager.check_metrics({"activeConnections": 150, "cacheHitRatio": 50})
    assert len(created) == 2
    assert manager.get_counts()["critical"] == 2

    alert_id = created[0].id
    assert manager.acknowledge_by_id(alert_id) is True
    assert manager.find_by_id(alert_id).acknowledged is True
    assert manager.get_counts()["critical"] == 1

    cleared = manager.acknowledge_all()
    assert cleared == 1
    assert manager.get_counts()["total"] == 0


def test_alert_to_dict_includes_id():
    alert = Alert("t", "m", AlertSeverity.INFO, "unit")
    data = alert.to_dict()
    assert data["id"] == alert.id
    assert data["acknowledged"] is False
    assert data["severity"] == "info"


def test_database_monitor_poll_once_sqlite(sqlite_db):
    monitor = DatabaseMonitor(sqlite_db)
    monitor.monitoring = True
    data = asyncio.run(monitor.poll_once())

    assert "metrics" in data
    assert data["metrics"].get("databaseType") == "sqlite" or data["metrics"].get(
        "connected"
    ) in (True, False)
    assert data["health"]["status"] in {"healthy", "degraded", "unhealthy", "unknown"}
    assert "checks" in data["health"]
    assert isinstance(data["alerts"], list)
    assert data["alertCounts"]["total"] == len(data["alerts"])

    summary = monitor.get_status_summary()
    assert summary["monitoring"] is True
    assert summary["healthStatus"] == data["health"]["status"]


def test_emit_alert_invokes_callback():
    manager = AlertManager()
    seen = []
    manager.add_alert_callback(lambda a: seen.append(a.title))
    manager.emit_alert(
        Alert("Health down", "unhealthy", AlertSeverity.CRITICAL, "health_monitor")
    )
    assert seen == ["Health down"]


def test_alert_manager_apply_and_validate_thresholds():
    manager = AlertManager()
    custom = {
        "connection_count": {"warning": 10, "critical": 20},
        "cache_hit_ratio": {"warning": 90, "critical": 50},
    }
    manager.apply_thresholds(custom)
    assert manager.get_thresholds()["connection_count"]["warning"] == 10

    bad = {"connection_count": {"warning": 100, "critical": 10}}
    errors = manager.validate_thresholds(bad)
    assert errors
    assert manager.validate_thresholds(custom) == []

    # Custom thresholds trip earlier
    created = manager.check_metrics({"activeConnections": 15})
    assert len(created) == 1
    assert created[0].severity == AlertSeverity.WARNING


def test_alert_manager_query_time_and_disk_usage():
    manager = AlertManager()
    created = manager.check_metrics(
        {"queryTime": 6000, "diskUsage": 80, "cacheHitRatio": 99}
    )
    titles = {a.title for a in created}
    assert "Critical Query Latency" in titles
    assert "Elevated Disk Usage" in titles


def test_notification_dispatcher_channels(isolated_secure_store):
    _store, _ = isolated_secure_store
    seen = []
    dispatcher = NotificationDispatcher({"desktop": True, "in_app": True})
    dispatcher.set_desktop_handler(
        lambda title, message, severity: seen.append((title, severity))
    )
    alert = Alert("High load", "connections spike", AlertSeverity.WARNING, "unit")
    fired = dispatcher.notify(alert)
    assert fired == ["in_app", "desktop"]
    assert len(dispatcher.in_app_log) == 1
    assert seen == [("High load", "warning")]

    dispatcher.configure({"desktop": False, "in_app": True})
    fired2 = dispatcher.notify(
        Alert("Quiet", "desktop off", AlertSeverity.INFO, "unit")
    )
    assert fired2 == ["in_app"]
    assert len(seen) == 1


def test_alert_thresholds_persist_via_secure_store(isolated_secure_store):
    store, _ = isolated_secure_store
    settings = store.get_settings()
    assert "alert_thresholds" in settings
    assert "alert_channels" in settings
    settings["alert_thresholds"] = {
        **copy.deepcopy(DEFAULT_ALERT_THRESHOLDS),
        "connection_count": {"warning": 5, "critical": 15},
    }
    settings["alert_channels"] = {**DEFAULT_ALERT_CHANNELS, "desktop": False}
    store.set_settings(settings)

    reloaded = store.get_settings()
    assert reloaded["alert_thresholds"]["connection_count"]["warning"] == 5
    assert reloaded["alert_channels"]["desktop"] is False

    manager = AlertManager(reloaded["alert_thresholds"])
    created = manager.check_metrics({"activeConnections": 8})
    assert len(created) == 1
    assert created[0].severity == AlertSeverity.WARNING


def test_monitoring_widget_offscreen_smoke(isolated_secure_store, monkeypatch):
    _store, _ = isolated_secure_store
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from db_storage_manager.gui.monitoring import MonitoringWidget

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: 0))

    app = QApplication.instance() or QApplication([])
    widget = MonitoringWidget([])
    assert widget.status_label.text()
    assert widget.alerts_table.columnCount() == 5
    assert widget.health_table.columnCount() == 3
    assert widget.start_button.isEnabled() is False
    assert widget.stop_button.isEnabled() is False
    assert "connection_count" in widget._threshold_spins
    assert widget.desktop_channel_check.isChecked()
    assert widget.in_app_channel_check.isChecked()
    assert widget.tabs.count() >= 6

    # Threshold edit + save round-trip through SecureStore
    widget._threshold_spins["connection_count"]["warning"].setValue(12)
    widget._threshold_spins["connection_count"]["critical"].setValue(30)
    widget._save_thresholds()
    saved = widget.secure_store.get_settings()["alert_thresholds"]
    assert saved["connection_count"]["warning"] == 12
    assert saved["connection_count"]["critical"] == 30

    widget.desktop_channel_check.setChecked(False)
    widget._save_channels()
    assert widget.secure_store.get_settings()["alert_channels"]["desktop"] is False

    # Fire a notification through the dispatcher wired to the widget
    fired = widget.notification_dispatcher.notify(
        Alert("Smoke", "channel test", AlertSeverity.INFO, "test")
    )
    assert "in_app" in fired
    widget._refresh_notification_log()
    assert widget.notification_log.rowCount() == 1
    assert len(widget.notification_dispatcher.in_app_log) == 1

    widget.update_connections(
        [
            {
                "id": "c1",
                "name": "Demo",
                "type": "sqlite",
                "database": ":memory:",
            }
        ]
    )
    widget.connection_combo.setCurrentIndex(1)
    assert widget.start_button.isEnabled() is True
    widget.close()
    app.processEvents()
