"""Tests for monitoring alerts and GUI presentation wiring."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.db.factory import DatabaseConnectionFactory
from db_storage_manager.monitoring import (
    Alert,
    AlertManager,
    AlertSeverity,
    DatabaseMonitor,
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


def test_monitoring_widget_offscreen_smoke():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from db_storage_manager.gui.monitoring import MonitoringWidget

    app = QApplication.instance() or QApplication([])
    widget = MonitoringWidget([])
    assert widget.status_label.text()
    assert widget.alerts_table.columnCount() == 5
    assert widget.health_table.columnCount() == 3
    assert widget.start_button.isEnabled() is False
    assert widget.stop_button.isEnabled() is False

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
