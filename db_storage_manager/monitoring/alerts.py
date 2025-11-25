"""
Alert system for database monitoring
"""

from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from enum import Enum


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert:
    """Database alert"""

    def __init__(self, title: str, message: str, severity: AlertSeverity, source: str = "system"):
        self.title = title
        self.message = message
        self.severity = severity
        self.source = source
        self.timestamp = datetime.now().isoformat()
        self.acknowledged = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary"""
        return {
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

    def check_metrics(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Check metrics against thresholds and generate alerts"""
        new_alerts = []
        
        # Check connection count
        active_connections = metrics.get("activeConnections", 0)
        if active_connections >= self.thresholds["connection_count"]["critical"]:
            alert = Alert(
                "High Connection Count",
                f"Database has {active_connections} active connections (critical threshold: {self.thresholds['connection_count']['critical']})",
                AlertSeverity.CRITICAL,
                "connection_monitor"
            )
            new_alerts.append(alert)
        elif active_connections >= self.thresholds["connection_count"]["warning"]:
            alert = Alert(
                "Elevated Connection Count",
                f"Database has {active_connections} active connections (warning threshold: {self.thresholds['connection_count']['warning']})",
                AlertSeverity.WARNING,
                "connection_monitor"
            )
            new_alerts.append(alert)
        
        # Check cache hit ratio
        cache_hit_ratio = metrics.get("cacheHitRatio", 100)
        if cache_hit_ratio <= self.thresholds["cache_hit_ratio"]["critical"]:
            alert = Alert(
                "Low Cache Hit Ratio",
                f"Cache hit ratio is {cache_hit_ratio:.2f}% (critical threshold: {self.thresholds['cache_hit_ratio']['critical']}%)",
                AlertSeverity.CRITICAL,
                "performance_monitor"
            )
            new_alerts.append(alert)
        elif cache_hit_ratio <= self.thresholds["cache_hit_ratio"]["warning"]:
            alert = Alert(
                "Suboptimal Cache Hit Ratio",
                f"Cache hit ratio is {cache_hit_ratio:.2f}% (warning threshold: {self.thresholds['cache_hit_ratio']['warning']}%)",
                AlertSeverity.WARNING,
                "performance_monitor"
            )
            new_alerts.append(alert)
        
        # Add new alerts
        for alert in new_alerts:
            self.alerts.append(alert)
            # Trigger callbacks
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception:
                    pass
        
        return new_alerts

    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unacknowledged) alerts"""
        return [a for a in self.alerts if not a.acknowledged]

    def get_critical_alerts(self) -> List[Alert]:
        """Get all critical alerts"""
        return [a for a in self.alerts if a.severity == AlertSeverity.CRITICAL and not a.acknowledged]

    def acknowledge_alert(self, alert_index: int) -> None:
        """Acknowledge an alert"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True

    def set_threshold(self, metric: str, level: str, value: float) -> None:
        """Set threshold for a metric"""
        if metric not in self.thresholds:
            self.thresholds[metric] = {}
        self.thresholds[metric][level] = value

    def get_thresholds(self) -> Dict[str, Dict[str, float]]:
        """Get all thresholds"""
        return self.thresholds.copy()

