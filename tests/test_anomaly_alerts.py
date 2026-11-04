"""Local sample history and the anomaly rules."""

from db_storage_manager.monitoring.alerts import AlertSeverity
from db_storage_manager.monitoring.anomaly import (
    detect_anomalies,
    record_and_detect,
    sample_from_metrics,
)


def _history(connections, ratio=99.0, size=50_000_000, query_ms=10.0, n=6):
    rows = []
    for i in range(n - 1):
        rows.append(
            {
                "timestamp": f"2026-11-04T00:0{i}:00",
                "activeConnections": float(connections),
                "cacheHitRatio": float(ratio),
                "databaseSize": float(size),
                "queryTime": float(query_ms),
            }
        )
    return rows


def test_sample_drops_sql_text():
    sample = sample_from_metrics(
        {
            "timestamp": "2026-11-04T00:00:00",
            "activeConnections": 4,
            "query": "SELECT secret FROM users",
            "password": "nope",
        }
    )
    assert "query" not in sample
    assert "password" not in sample
    assert sample["activeConnections"] == 4.0


def test_short_history_does_not_alert():
    assert detect_anomalies(_history(3, n=4) + [{"activeConnections": 100}]) == []


def test_connection_jump_cache_drop_growth_and_slow_query():
    base = _history(4, ratio=99, size=40_000_000, query_ms=20)
    base.append(
        {
            "timestamp": "2026-11-04T01:00:00",
            "activeConnections": 10,
            "cacheHitRatio": 50,
            "databaseSize": 55_000_000,
            "queryTime": 6000,
        }
    )
    found = {item["metric"]: item["severity"] for item in detect_anomalies(base)}
    assert found["connections"] == "warning"
    assert found["cache_hit_ratio"] == "critical"
    assert found["growth"] == "warning"
    assert found["slow_queries"] == "critical"


def test_samples_stay_in_the_given_directory(tmp_path):
    metrics = {
        "timestamp": "2026-11-04T00:00:00",
        "activeConnections": 2,
        "cacheHitRatio": 99,
        "databaseSize": 1000,
        "queryTime": 1,
    }
    for _ in range(6):
        anomalies = record_and_detect("conn/../one", metrics, directory=tmp_path)
    assert anomalies == []
    stored = list(tmp_path.glob("*.json"))
    assert len(stored) == 1
    assert ".." not in stored[0].name
    assert stored[0].stat().st_mode & 0o777 == 0o600


def test_monitor_emits_anomaly_from_local_history(tmp_path, monkeypatch):
    import db_storage_manager.monitoring.anomaly as anomaly_mod
    from db_storage_manager.monitoring.monitor import DatabaseMonitor

    monkeypatch.setattr(anomaly_mod, "_default_directory", lambda: tmp_path)

    class Config:
        id = "primary"
        type = "sqlite"

    class Connection:
        config = Config()
        connected = True

        async def connect(self):
            return None

    monitor = DatabaseMonitor(Connection())
    metrics = {
        "timestamp": "2026-11-04T00:00:00",
        "activeConnections": 4,
        "cacheHitRatio": 99,
        "databaseSize": 40_000_000,
        "queryTime": 10,
    }
    for _ in range(5):
        monitor._emit_anomalies(metrics)
    assert monitor.alert_manager.get_active_alerts() == []
    monitor._emit_anomalies(
        {
            **metrics,
            "activeConnections": 40,
            "queryTime": 8000,
        }
    )
    titles = [alert.title for alert in monitor.alert_manager.get_active_alerts()]
    assert "Connection count jumped" in titles
    assert "Slow query" in titles
    assert all(
        alert.severity == AlertSeverity.CRITICAL or alert.source == "anomaly"
        for alert in monitor.alert_manager.get_active_alerts()
    )
