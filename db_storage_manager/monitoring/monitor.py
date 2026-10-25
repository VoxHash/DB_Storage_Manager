"""
Main database monitoring system
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from ..db.base import DatabaseConnection
from .alerts import Alert, AlertManager, AlertSeverity
from .health import HealthChecker
from .metrics import MetricsCollector


class DatabaseMonitor:
    """Main database monitoring system"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.metrics_collector = MetricsCollector(connection)
        self.alert_manager = AlertManager()
        self.health_checker = HealthChecker(connection)
        self.monitoring = False
        self.monitoring_task: Optional[asyncio.Task] = None
        self._on_metrics: Optional[Callable[[Dict[str, Any]], None]] = None
        self._last_health_alert_status: Optional[str] = None

    async def poll_once(self) -> Dict[str, Any]:
        """Collect one metrics + health sample and evaluate alert thresholds.

        Intended for Qt timers (or other drivers) that cannot keep a long-lived
        asyncio event loop running in the background.
        """
        if not self.connection.connected:
            await self.connection.connect()

        metrics = await self.metrics_collector.collect_metrics()
        self.metrics_collector.metrics_history.append(metrics)
        if len(self.metrics_collector.metrics_history) > 1000:
            self.metrics_collector.metrics_history = (
                self.metrics_collector.metrics_history[-1000:]
            )

        if self._on_metrics:
            try:
                self._on_metrics(metrics)
            except Exception:
                pass

        self.alert_manager.check_metrics(metrics)

        health = await self.health_checker.check_health()
        status = health.get("status")
        if status == "unhealthy" and self._last_health_alert_status != "unhealthy":
            self.alert_manager.emit_alert(
                Alert(
                    "Database Health Check Failed",
                    "Database health check returned unhealthy status",
                    AlertSeverity.CRITICAL,
                    "health_monitor",
                )
            )
        self._last_health_alert_status = status

        return self.get_dashboard_data()

    async def start_monitoring(
        self,
        metrics_interval: int = 60,
        health_interval: int = 300,
        on_alert: Optional[Callable[[Alert], None]] = None,
        on_metrics: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Start monitoring database"""
        if self.monitoring:
            return

        self.monitoring = True
        self._on_metrics = on_metrics

        if on_alert:
            self.alert_manager.add_alert_callback(on_alert)

        # Start metrics collection
        metrics_task = asyncio.create_task(
            self.metrics_collector.start_collecting(
                interval_seconds=metrics_interval, callback=on_metrics
            )
        )

        # Start health checks
        async def health_check_loop():
            while self.monitoring:
                try:
                    health = await self.health_checker.check_health()
                    status = health.get("status")
                    if (
                        status == "unhealthy"
                        and self._last_health_alert_status != "unhealthy"
                    ):
                        self.alert_manager.emit_alert(
                            Alert(
                                "Database Health Check Failed",
                                "Database health check returned unhealthy status",
                                AlertSeverity.CRITICAL,
                                "health_monitor",
                            )
                        )
                    self._last_health_alert_status = status
                except Exception:
                    pass
                await asyncio.sleep(health_interval)

        health_task = asyncio.create_task(health_check_loop())

        # Start alert checking
        async def alert_check_loop():
            while self.monitoring:
                try:
                    metrics = self.metrics_collector.get_latest_metrics()
                    if metrics:
                        self.alert_manager.check_metrics(metrics)
                except Exception:
                    pass
                await asyncio.sleep(metrics_interval)

        alert_task = asyncio.create_task(alert_check_loop())

        self.monitoring_task = asyncio.create_task(
            asyncio.gather(metrics_task, health_task, alert_task)
        )

    async def stop_monitoring(self) -> None:
        """Stop monitoring database"""
        self.monitoring = False
        self.metrics_collector.stop_collecting()

        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for monitoring dashboard"""
        latest_metrics = self.metrics_collector.get_latest_metrics()
        current_health = self.health_checker.get_current_health()
        active_alerts = self.alert_manager.get_active_alerts()
        counts = self.alert_manager.get_counts()

        return {
            "metrics": latest_metrics or {},
            "health": current_health
            or {
                "status": "unknown",
                "checks": {},
                "timestamp": None,
            },
            "alerts": [alert.to_dict() for alert in active_alerts],
            "alertCounts": counts,
            "monitoring": self.monitoring,
            "metricsHistory": self.metrics_collector.get_metrics_history(limit=50),
            "healthHistory": self.health_checker.get_health_history(limit=20),
        }

    def get_status_summary(self) -> Dict[str, Any]:
        """Compact status for the monitoring banner."""
        data = self.get_dashboard_data()
        health = data.get("health") or {}
        return {
            "monitoring": self.monitoring,
            "healthStatus": health.get("status", "unknown"),
            "alertCounts": data.get("alertCounts", {}),
            "lastMetricsAt": (data.get("metrics") or {}).get("timestamp"),
            "lastHealthAt": health.get("timestamp"),
        }


    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        metrics_history = self.metrics_collector.get_metrics_history(limit=100)

        if not metrics_history:
            return {
                "averageConnections": 0,
                "averageQueryTime": 0,
                "averageCacheHitRatio": 0,
            }

        connections = [m.get("activeConnections", 0) for m in metrics_history]
        cache_ratios = [
            m.get("cacheHitRatio", 0)
            for m in metrics_history
            if m.get("cacheHitRatio") is not None
        ]

        return {
            "averageConnections": (
                sum(connections) / len(connections) if connections else 0
            ),
            "maxConnections": max(connections) if connections else 0,
            "averageCacheHitRatio": (
                sum(cache_ratios) / len(cache_ratios) if cache_ratios else 0
            ),
            "dataPoints": len(metrics_history),
        }
