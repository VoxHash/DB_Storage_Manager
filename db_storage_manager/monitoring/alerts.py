"""
Alert system for database monitoring
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class AlertSeverity(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert:
    """Database alert"""

    def __init__(
        self, title: str, message: str, severity: AlertSeverity, source: str = "system"
    ):
        self.id = str(uuid.uuid4())
        self.title = title
        self.message = message
        self.severity = severity
        self.source = source
        self.timestamp = datetime.now().isoformat()
        self.acknowledged = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


class AlertManager:
    """Manage database alerts"""

    def __init__(self):
        self.alerts: List[Alert] = []
        self.alert_callbacks: List[Callable[[Alert], None]] = []
        self.thresholds: Dict[str, Dict[str, float]] = {
            "connection_count": {"warning": 50, "critical": 100},
            "query_time": {"warning": 1000, "critical": 5000},  # milliseconds
            "cache_hit_ratio": {"warning": 80, "critical": 60},  # percentage
            "disk_usage": {"warning": 75, "critical": 90},  # percentage
        }

    def add_alert_callback(self, callback: Callable[[Alert], None]) -> None:
        """Add callback for new alerts"""
        self.alert_callbacks.append(callback)

    def emit_alert(self, alert: Alert) -> Alert:
        """Record an alert and notify callbacks."""
        self.alerts.append(alert)
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception:
                pass
        return alert

    def check_metrics(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Check metrics against thresholds and generate alerts"""
        new_alerts: List[Alert] = []

        # Check connection count
        active_connections = metrics.get("activeConnections", 0)
        if active_connections >= self.thresholds["connection_count"]["critical"]:
            new_alerts.append(
                Alert(
                    "High Connection Count",
                    f"Database has {active_connections} active connections (critical threshold: {self.thresholds['connection_count']['critical']})",
                    AlertSeverity.CRITICAL,
                    "connection_monitor",
                )
            )
        elif active_connections >= self.thresholds["connection_count"]["warning"]:
            new_alerts.append(
                Alert(
                    "Elevated Connection Count",
                    f"Database has {active_connections} active connections (warning threshold: {self.thresholds['connection_count']['warning']})",
                    AlertSeverity.WARNING,
                    "connection_monitor",
                )
            )

        # Check cache hit ratio
        cache_hit_ratio = metrics.get("cacheHitRatio", 100)
        if cache_hit_ratio <= self.thresholds["cache_hit_ratio"]["critical"]:
            new_alerts.append(
                Alert(
                    "Low Cache Hit Ratio",
                    f"Cache hit ratio is {cache_hit_ratio:.2f}% (critical threshold: {self.thresholds['cache_hit_ratio']['critical']}%)",
                    AlertSeverity.CRITICAL,
                    "performance_monitor",
                )
            )
        elif cache_hit_ratio <= self.thresholds["cache_hit_ratio"]["warning"]:
            new_alerts.append(
                Alert(
                    "Suboptimal Cache Hit Ratio",
                    f"Cache hit ratio is {cache_hit_ratio:.2f}% (warning threshold: {self.thresholds['cache_hit_ratio']['warning']}%)",
                    AlertSeverity.WARNING,
                    "performance_monitor",
                )
            )

        emitted: List[Alert] = []
        for alert in new_alerts:
            if self._has_active_alert(alert.title, alert.source):
                continue
            self.emit_alert(alert)
            emitted.append(alert)

        return emitted

    def _has_active_alert(self, title: str, source: str) -> bool:
        """True when an unacknowledged alert with the same title/source exists."""
        return any(
            not a.acknowledged and a.title == title and a.source == source
            for a in self.alerts
        )

    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unacknowledged) alerts"""
        return [a for a in self.alerts if not a.acknowledged]

    def get_critical_alerts(self) -> List[Alert]:
        """Get all critical alerts"""
        return [
            a
            for a in self.alerts
            if a.severity == AlertSeverity.CRITICAL and not a.acknowledged
        ]

    def get_counts(self) -> Dict[str, int]:
        """Count unacknowledged alerts by severity."""
        counts = {"critical": 0, "warning": 0, "info": 0, "total": 0}
        for alert in self.get_active_alerts():
            key = alert.severity.value
            if key in counts:
                counts[key] += 1
            counts["total"] += 1
        return counts

    def acknowledge_alert(self, alert_index: int) -> None:
        """Acknowledge an alert by index in the full alert list"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True

    def acknowledge_by_id(self, alert_id: str) -> bool:
        """Acknowledge a single alert by its id. Returns True if found."""
        for alert in self.alerts:
            if alert.id == alert_id and not alert.acknowledged:
                alert.acknowledged = True
                return True
        return False

    def acknowledge_all(self) -> int:
        """Acknowledge every active alert. Returns how many were acknowledged."""
        count = 0
        for alert in self.alerts:
            if not alert.acknowledged:
                alert.acknowledged = True
                count += 1
        return count

    def find_by_id(self, alert_id: str) -> Optional[Alert]:
        """Look up an alert by id."""
        for alert in self.alerts:
            if alert.id == alert_id:
                return alert
        return None

    def set_threshold(self, metric: str, level: str, value: float) -> None:
        """Set threshold for a metric"""
        if metric not in self.thresholds:
            self.thresholds[metric] = {}
        self.thresholds[metric][level] = value

    def get_thresholds(self) -> Dict[str, Dict[str, float]]:
        """Get all thresholds"""
        return self.thresholds.copy()
