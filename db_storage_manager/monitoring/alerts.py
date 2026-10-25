"""
Alert system for database monitoring
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

DEFAULT_ALERT_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "connection_count": {"warning": 50, "critical": 100},
    "query_time": {"warning": 1000, "critical": 5000},  # milliseconds
    "cache_hit_ratio": {"warning": 80, "critical": 60},  # percentage (lower is worse)
    "disk_usage": {"warning": 75, "critical": 90},  # percentage
}

# Metrics where a higher value is worse
_HIGH_IS_BAD = frozenset({"connection_count", "query_time", "disk_usage"})
# Metrics where a lower value is worse
_LOW_IS_BAD = frozenset({"cache_hit_ratio"})


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

    def __init__(self, thresholds: Optional[Dict[str, Dict[str, float]]] = None):
        self.alerts: List[Alert] = []
        self.alert_callbacks: List[Callable[[Alert], None]] = []
        self.thresholds: Dict[str, Dict[str, float]] = copy.deepcopy(
            DEFAULT_ALERT_THRESHOLDS
        )
        if thresholds:
            self.apply_thresholds(thresholds)

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

    def apply_thresholds(self, thresholds: Dict[str, Dict[str, float]]) -> None:
        """Replace known metric thresholds from a settings-shaped dict."""
        for metric, levels in thresholds.items():
            if not isinstance(levels, dict):
                continue
            if metric not in self.thresholds:
                self.thresholds[metric] = {}
            for level, value in levels.items():
                if level not in ("warning", "critical"):
                    continue
                try:
                    self.thresholds[metric][level] = float(value)
                except (TypeError, ValueError):
                    continue

    def validate_thresholds(
        self, thresholds: Optional[Dict[str, Dict[str, float]]] = None
    ) -> List[str]:
        """Return human-readable validation errors (empty = OK)."""
        data = thresholds if thresholds is not None else self.thresholds
        errors: List[str] = []
        for metric, levels in data.items():
            if not isinstance(levels, dict):
                errors.append(f"{metric}: expected warning/critical map")
                continue
            try:
                warning = float(levels.get("warning"))
                critical = float(levels.get("critical"))
            except (TypeError, ValueError):
                errors.append(f"{metric}: warning and critical must be numbers")
                continue
            if metric in _HIGH_IS_BAD and warning >= critical:
                errors.append(
                    f"{metric}: warning ({warning}) must be less than critical ({critical})"
                )
            if metric in _LOW_IS_BAD and warning <= critical:
                errors.append(
                    f"{metric}: warning ({warning}) must be greater than critical ({critical})"
                )
        return errors

    def check_metrics(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Check metrics against thresholds and generate alerts"""
        new_alerts: List[Alert] = []

        # Check connection count
        if "activeConnections" in metrics:
            active_connections = metrics.get("activeConnections", 0) or 0
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
        if "cacheHitRatio" in metrics and metrics.get("cacheHitRatio") is not None:
            cache_hit_ratio = float(metrics.get("cacheHitRatio", 100))
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

        # Check query time when present (ms)
        if "queryTime" in metrics and metrics.get("queryTime") is not None:
            query_time = float(metrics.get("queryTime", 0))
            if query_time >= self.thresholds["query_time"]["critical"]:
                new_alerts.append(
                    Alert(
                        "Critical Query Latency",
                        f"Query time is {query_time:.0f}ms (critical threshold: {self.thresholds['query_time']['critical']}ms)",
                        AlertSeverity.CRITICAL,
                        "performance_monitor",
                    )
                )
            elif query_time >= self.thresholds["query_time"]["warning"]:
                new_alerts.append(
                    Alert(
                        "Elevated Query Latency",
                        f"Query time is {query_time:.0f}ms (warning threshold: {self.thresholds['query_time']['warning']}ms)",
                        AlertSeverity.WARNING,
                        "performance_monitor",
                    )
                )

        # Check disk usage when present (%)
        if "diskUsage" in metrics and metrics.get("diskUsage") is not None:
            disk_usage = float(metrics.get("diskUsage", 0))
            if disk_usage >= self.thresholds["disk_usage"]["critical"]:
                new_alerts.append(
                    Alert(
                        "Critical Disk Usage",
                        f"Disk usage is {disk_usage:.1f}% (critical threshold: {self.thresholds['disk_usage']['critical']}%)",
                        AlertSeverity.CRITICAL,
                        "storage_monitor",
                    )
                )
            elif disk_usage >= self.thresholds["disk_usage"]["warning"]:
                new_alerts.append(
                    Alert(
                        "Elevated Disk Usage",
                        f"Disk usage is {disk_usage:.1f}% (warning threshold: {self.thresholds['disk_usage']['warning']}%)",
                        AlertSeverity.WARNING,
                        "storage_monitor",
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
        self.thresholds[metric][level] = float(value)

    def get_thresholds(self) -> Dict[str, Dict[str, float]]:
        """Get all thresholds (deep copy safe for UI editing)."""
        return copy.deepcopy(self.thresholds)
