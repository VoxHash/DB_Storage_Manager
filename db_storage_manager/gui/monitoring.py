"""
Real-time monitoring dashboard widget
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..analysis import (
    CapacityPlanner,
    IndexOptimizer,
    QueryPerformanceAnalyzer,
    StorageGrowthPredictor,
)
from ..db.base import ConnectionConfig
from ..db.factory import DatabaseConnectionFactory
from ..i18n.manager import get_i18n_manager
from ..monitoring import Alert, DatabaseMonitor
from .utils import apply_glassmorphism

_CONNECTION_FIELDS = {
    "id",
    "name",
    "type",
    "host",
    "port",
    "database",
    "username",
    "password",
    "connection_string",
    "ssh_config",
    "extra",
}

_METRIC_LABELS = {
    "activeConnections": "Active connections",
    "activeQueries": "Active queries",
    "idleConnections": "Idle connections",
    "transactionsCommitted": "Transactions committed",
    "transactionsRolledBack": "Transactions rolled back",
    "transactionsPerSecond": "Transactions / sec",
    "blocksRead": "Blocks read",
    "blocksHit": "Blocks hit",
    "databaseSize": "Database size (bytes)",
    "cacheHitRatio": "Cache hit ratio (%)",
    "totalQueries": "Total queries",
    "connected": "Connected",
    "databaseType": "Database type",
}

_SEVERITY_COLORS = {
    "critical": QColor(190, 55, 55),
    "warning": QColor(190, 140, 40),
    "info": QColor(55, 120, 180),
}

_STATUS_COLORS = {
    "healthy": QColor(45, 140, 75),
    "degraded": QColor(190, 140, 40),
    "unhealthy": QColor(190, 55, 55),
    "unknown": QColor(120, 120, 120),
}


def _connection_config_kwargs(connection: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in connection.items() if k in _CONNECTION_FIELDS}


def _format_metric_value(key: str, value: Any) -> str:
    if key == "cacheHitRatio" and isinstance(value, (int, float)):
        return f"{value:.2f}%"
    if key == "databaseSize" and isinstance(value, (int, float)):
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


class MonitoringWidget(QWidget):
    """Real-time monitoring widget"""

    def __init__(self, connections):
        super().__init__()
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.current_connection = None
        self.monitor: Optional[DatabaseMonitor] = None
        self._db = None
        self.performance_analyzer = None
        self.index_optimizer = None
        self.growth_predictor = None
        self.capacity_planner = None
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        t = self.i18n.translate

        connection_layout = QHBoxLayout()
        connection_layout.addWidget(QLabel(f"{t('monitoring.connection')}"))
        self.connection_combo = QComboBox()
        self.connection_combo.addItem(t("monitoring.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        self.connection_combo.currentIndexChanged.connect(self._on_connection_changed)
        connection_layout.addWidget(self.connection_combo)

        self.start_button = QPushButton(t("monitoring.start_monitoring"))
        self.start_button.clicked.connect(self._start_monitoring)
        self.start_button.setEnabled(False)
        connection_layout.addWidget(self.start_button)

        self.stop_button = QPushButton(t("monitoring.stop_monitoring"))
        self.stop_button.clicked.connect(self._stop_monitoring)
        self.stop_button.setEnabled(False)
        connection_layout.addWidget(self.stop_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        self.status_label = QLabel(t("monitoring.status_idle"))
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("monitoringStatus")
        layout.addWidget(self.status_label)

        tabs = QTabWidget()
        self.tabs = tabs

        metrics_widget = QWidget()
        metrics_layout = QVBoxLayout(metrics_widget)
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(
            [t("monitoring.metric"), t("monitoring.value")]
        )
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.metrics_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        metrics_layout.addWidget(self.metrics_table)
        tabs.addTab(metrics_widget, t("monitoring.metrics"))

        alerts_widget = QWidget()
        alerts_layout = QVBoxLayout(alerts_widget)
        alerts_actions = QHBoxLayout()
        self.acknowledge_button = QPushButton(t("monitoring.acknowledge_selected"))
        self.acknowledge_button.clicked.connect(self._acknowledge_selected)
        self.acknowledge_button.setEnabled(False)
        alerts_actions.addWidget(self.acknowledge_button)
        self.acknowledge_all_button = QPushButton(t("monitoring.acknowledge_all"))
        self.acknowledge_all_button.clicked.connect(self._acknowledge_all)
        self.acknowledge_all_button.setEnabled(False)
        alerts_actions.addWidget(self.acknowledge_all_button)
        self.refresh_button = QPushButton(t("monitoring.refresh_now"))
        self.refresh_button.clicked.connect(self._poll_now)
        self.refresh_button.setEnabled(False)
        alerts_actions.addWidget(self.refresh_button)
        alerts_actions.addStretch()
        alerts_layout.addLayout(alerts_actions)

        self.alerts_table = QTableWidget()
        self.alerts_table.setColumnCount(5)
        self.alerts_table.setHorizontalHeaderLabels(
            [
                t("monitoring.alert_time"),
                t("monitoring.severity"),
                t("monitoring.title"),
                t("monitoring.message"),
                t("monitoring.source"),
            ]
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.alerts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alerts_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.alerts_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.alerts_table.itemSelectionChanged.connect(self._on_alert_selection_changed)
        alerts_layout.addWidget(self.alerts_table)
        tabs.addTab(alerts_widget, t("monitoring.alerts"))

        performance_widget = QWidget()
        performance_layout = QVBoxLayout(performance_widget)
        self.performance_text = QTextEdit()
        self.performance_text.setReadOnly(True)
        performance_layout.addWidget(self.performance_text)
        tabs.addTab(performance_widget, t("monitoring.performance"))

        health_widget = QWidget()
        health_layout = QVBoxLayout(health_widget)
        self.health_overall_label = QLabel(t("monitoring.health_unknown"))
        health_layout.addWidget(self.health_overall_label)
        self.health_table = QTableWidget()
        self.health_table.setColumnCount(3)
        self.health_table.setHorizontalHeaderLabels(
            [
                t("monitoring.check"),
                t("monitoring.status"),
                t("monitoring.detail"),
            ]
        )
        self.health_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.health_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        health_layout.addWidget(self.health_table)
        tabs.addTab(health_widget, t("monitoring.health"))

        layout.addWidget(tabs)

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._poll_now)
        self.update_timer.setInterval(5000)

    def _on_connection_changed(self, index):
        """Handle connection selection change"""
        if index > 0:
            self.current_connection = self.connection_combo.itemData(index)
            self.start_button.setEnabled(self.monitor is None)
        else:
            self.current_connection = None
            self.start_button.setEnabled(False)

    def _start_monitoring(self):
        """Start monitoring via timer-driven poll_once against real modules."""
        if not self.current_connection:
            return

        try:
            config = ConnectionConfig(**_connection_config_kwargs(self.current_connection))
            db = DatabaseConnectionFactory.create_connection(config)
            asyncio.run(db.connect())

            self._db = db
            self.monitor = DatabaseMonitor(db)
            self.monitor.monitoring = True
            self.monitor.alert_manager.add_alert_callback(self._on_alert)
            self.monitor._on_metrics = self._on_metrics
            self.performance_analyzer = QueryPerformanceAnalyzer(db)
            self.index_optimizer = IndexOptimizer(db)
            self.growth_predictor = StorageGrowthPredictor(db)
            self.capacity_planner = CapacityPlanner(db)

            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.acknowledge_all_button.setEnabled(True)
            self.connection_combo.setEnabled(False)

            self._poll_now()
            self.update_timer.start()
        except Exception as e:
            self._cleanup_monitor()
            QMessageBox.critical(self, self.i18n.translate("common.error"), str(e))

    def _stop_monitoring(self):
        """Stop monitoring"""
        self.update_timer.stop()
        if self.monitor:
            self.monitor.monitoring = False
            self.monitor.metrics_collector.stop_collecting()
        if self._db is not None:
            try:
                asyncio.run(self._db.disconnect())
            except Exception:
                pass
        self._cleanup_monitor()
        self.start_button.setEnabled(self.current_connection is not None)
        self.stop_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.acknowledge_button.setEnabled(False)
        self.acknowledge_all_button.setEnabled(False)
        self.connection_combo.setEnabled(True)
        self.status_label.setText(self.i18n.translate("monitoring.status_idle"))
        self.health_overall_label.setText(
            self.i18n.translate("monitoring.health_unknown")
        )

    def _cleanup_monitor(self):
        self.monitor = None
        self._db = None
        self.performance_analyzer = None
        self.index_optimizer = None
        self.growth_predictor = None
        self.capacity_planner = None

    def _poll_now(self):
        """Run one real poll cycle and refresh the tables."""
        if not self.monitor:
            return
        try:
            asyncio.run(self.monitor.poll_once())
            self._update_display()
        except Exception as e:
            self.status_label.setText(
                self.i18n.translate("monitoring.poll_failed", error=str(e))
            )

    def _on_alert(self, alert: Alert):
        """Handle new alert from AlertManager callbacks."""
        # Display refresh happens after poll_once; keep hook for future signals.
        _ = alert

    def _on_metrics(self, metrics: Dict[str, Any]):
        """Handle new metrics callback."""
        _ = metrics

    def _on_alert_selection_changed(self):
        has_selection = bool(self.alerts_table.selectionModel().selectedRows())
        self.acknowledge_button.setEnabled(bool(self.monitor) and has_selection)

    def _acknowledge_selected(self):
        if not self.monitor:
            return
        ids: List[str] = []
        for index in self.alerts_table.selectionModel().selectedRows():
            item = self.alerts_table.item(index.row(), 0)
            if item is None:
                continue
            alert_id = item.data(Qt.ItemDataRole.UserRole)
            if alert_id:
                ids.append(str(alert_id))
        for alert_id in ids:
            self.monitor.alert_manager.acknowledge_by_id(alert_id)
        self._update_display()

    def _acknowledge_all(self):
        if not self.monitor:
            return
        self.monitor.alert_manager.acknowledge_all()
        self._update_display()

    def _update_status_banner(self, dashboard_data: Dict[str, Any]):
        t = self.i18n.translate
        health = dashboard_data.get("health") or {}
        health_status = health.get("status", "unknown")
        counts = dashboard_data.get("alertCounts") or {}
        name = (
            self.current_connection.get("name", "")
            if self.current_connection
            else ""
        )
        self.status_label.setText(
            t(
                "monitoring.status_active",
                connection=name,
                health=health_status,
                critical=counts.get("critical", 0),
                warning=counts.get("warning", 0),
                info=counts.get("info", 0),
                total=counts.get("total", 0),
            )
        )
        color = _STATUS_COLORS.get(health_status, _STATUS_COLORS["unknown"])
        self.status_label.setStyleSheet(f"color: {color.name()}; font-weight: 600;")

        # Badge alerts tab with active count
        alerts_idx = 1
        total = counts.get("total", 0)
        label = t("monitoring.alerts")
        if total:
            label = f"{label} ({total})"
        self.tabs.setTabText(alerts_idx, label)

    def _update_display(self):
        """Update monitoring display from DatabaseMonitor dashboard data."""
        if not self.monitor:
            return

        dashboard_data = self.monitor.get_dashboard_data()
        self._update_status_banner(dashboard_data)

        metrics = dashboard_data.get("metrics") or {}
        rows = [(k, v) for k, v in metrics.items() if k != "timestamp"]
        self.metrics_table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            label = _METRIC_LABELS.get(key, key)
            self.metrics_table.setItem(row, 0, QTableWidgetItem(label))
            self.metrics_table.setItem(
                row, 1, QTableWidgetItem(_format_metric_value(key, value))
            )

        alerts = dashboard_data.get("alerts") or []
        self.alerts_table.setRowCount(len(alerts))
        for i, alert in enumerate(alerts):
            severity = str(alert.get("severity", "info")).lower()
            brush = QBrush(_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS["info"]))
            time_item = QTableWidgetItem(str(alert.get("timestamp", "")))
            time_item.setData(Qt.ItemDataRole.UserRole, alert.get("id"))
            sev_item = QTableWidgetItem(severity.upper())
            title_item = QTableWidgetItem(str(alert.get("title", "")))
            msg_item = QTableWidgetItem(str(alert.get("message", "")))
            src_item = QTableWidgetItem(str(alert.get("source", "")))
            for item in (time_item, sev_item, title_item, msg_item, src_item):
                item.setForeground(brush)
            self.alerts_table.setItem(i, 0, time_item)
            self.alerts_table.setItem(i, 1, sev_item)
            self.alerts_table.setItem(i, 2, title_item)
            self.alerts_table.setItem(i, 3, msg_item)
            self.alerts_table.setItem(i, 4, src_item)
        self._on_alert_selection_changed()

        health = dashboard_data.get("health") or {}
        health_status = health.get("status", "unknown")
        self.health_overall_label.setText(
            self.i18n.translate(
                "monitoring.health_overall", status=str(health_status).upper()
            )
        )
        health_color = _STATUS_COLORS.get(health_status, _STATUS_COLORS["unknown"])
        self.health_overall_label.setStyleSheet(
            f"color: {health_color.name()}; font-weight: 600;"
        )

        checks = health.get("checks") or {}
        self.health_table.setRowCount(len(checks))
        for row, (check_name, check_data) in enumerate(checks.items()):
            status = str(check_data.get("status", "unknown"))
            detail = str(check_data.get("message", ""))
            brush = QBrush(_STATUS_COLORS.get(status, _STATUS_COLORS["unknown"]))
            name_item = QTableWidgetItem(check_name.replace("_", " ").title())
            status_item = QTableWidgetItem(status)
            detail_item = QTableWidgetItem(detail)
            for item in (name_item, status_item, detail_item):
                item.setForeground(brush)
            self.health_table.setItem(row, 0, name_item)
            self.health_table.setItem(row, 1, status_item)
            self.health_table.setItem(row, 2, detail_item)

        if self.performance_analyzer:
            stats = self.performance_analyzer.get_query_statistics()
            summary = self.monitor.get_performance_summary()
            self.performance_text.setPlainText(
                "Query Performance Statistics:\n"
                f"Total Queries: {stats.get('totalQueries', 0)}\n"
                f"Average Execution Time: {stats.get('averageExecutionTime', 0):.2f}ms\n"
                f"Slow Queries: {stats.get('slowQueries', 0)}\n"
                f"Error Queries: {stats.get('errorQueries', 0)}\n"
                "\nMonitor Summary:\n"
                f"Average Connections: {summary.get('averageConnections', 0):.2f}\n"
                f"Max Connections: {summary.get('maxConnections', 0)}\n"
                f"Average Cache Hit Ratio: {summary.get('averageCacheHitRatio', 0):.2f}%\n"
                f"Data Points: {summary.get('dataPoints', 0)}\n"
            )

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        current = self.connection_combo.currentData()
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        self.connection_combo.addItem(
            self.i18n.translate("monitoring.select_connection")
        )
        selected_index = 0
        for i, conn in enumerate(self.connections, start=1):
            self.connection_combo.addItem(conn["name"], conn)
            if current and conn.get("id") == current.get("id"):
                selected_index = i
        self.connection_combo.setCurrentIndex(selected_index)
        self.connection_combo.blockSignals(False)
        self._on_connection_changed(selected_index)
