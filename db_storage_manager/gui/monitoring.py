"""
Real-time monitoring dashboard widget
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTabWidget,
    QTextEdit,
    QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from typing import Dict, List, Any

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..monitoring import DatabaseMonitor, Alert
from ..analysis import (
    QueryPerformanceAnalyzer,
    IndexOptimizer,
    StorageGrowthPredictor,
    CapacityPlanner,
)
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism


class MonitoringWidget(QWidget):
    """Real-time monitoring widget"""

    def __init__(self, connections):
        super().__init__()
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.current_connection = None
        self.monitor = None
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

        # Connection selection
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
        connection_layout.addWidget(self.start_button)

        self.stop_button = QPushButton(t("monitoring.stop_monitoring"))
        self.stop_button.clicked.connect(self._stop_monitoring)
        self.stop_button.setEnabled(False)
        connection_layout.addWidget(self.stop_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        # Create tabs for different monitoring views
        tabs = QTabWidget()

        # Metrics tab
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
        metrics_layout.addWidget(self.metrics_table)
        tabs.addTab(metrics_widget, t("monitoring.metrics"))

        # Alerts tab
        alerts_widget = QWidget()
        alerts_layout = QVBoxLayout(alerts_widget)
        self.alerts_table = QTableWidget()
        self.alerts_table.setColumnCount(4)
        self.alerts_table.setHorizontalHeaderLabels(
            [
                t("monitoring.alert_time"),
                t("monitoring.severity"),
                t("monitoring.title"),
                t("monitoring.message"),
            ]
        )
        self.alerts_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        alerts_layout.addWidget(self.alerts_table)
        tabs.addTab(alerts_widget, t("monitoring.alerts"))

        # Performance tab
        performance_widget = QWidget()
        performance_layout = QVBoxLayout(performance_widget)
        self.performance_text = QTextEdit()
        self.performance_text.setReadOnly(True)
        performance_layout.addWidget(self.performance_text)
        tabs.addTab(performance_widget, t("monitoring.performance"))

        # Health tab
        health_widget = QWidget()
        health_layout = QVBoxLayout(health_widget)
        self.health_table = QTableWidget()
        self.health_table.setColumnCount(2)
        self.health_table.setHorizontalHeaderLabels(
            [t("monitoring.check"), t("monitoring.status")]
        )
        self.health_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        health_layout.addWidget(self.health_table)
        tabs.addTab(health_widget, t("monitoring.health"))

        layout.addWidget(tabs)

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_display)
        self.update_timer.setInterval(5000)  # Update every 5 seconds

    def _on_connection_changed(self, index):
        """Handle connection selection change"""
        if index > 0:
            self.current_connection = self.connection_combo.itemData(index)
            self.start_button.setEnabled(True)
        else:
            self.current_connection = None
            self.start_button.setEnabled(False)

    def _start_monitoring(self):
        """Start monitoring"""
        if not self.current_connection:
            return

        try:
            config = ConnectionConfig(**self.current_connection)
            db = DatabaseConnectionFactory.create_connection(config)

            self.monitor = DatabaseMonitor(db)
            self.performance_analyzer = QueryPerformanceAnalyzer(db)
            self.index_optimizer = IndexOptimizer(db)
            self.growth_predictor = StorageGrowthPredictor(db)
            self.capacity_planner = CapacityPlanner(db)

            # Start monitoring
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.monitor.start_monitoring(
                    on_alert=self._on_alert, on_metrics=self._on_metrics
                )
            )

            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.update_timer.start()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, self.i18n.translate("common.error"), str(e))

    def _stop_monitoring(self):
        """Stop monitoring"""
        if self.monitor:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.monitor.stop_monitoring())

        self.update_timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _on_alert(self, alert: Alert):
        """Handle new alert"""
        # This will be called when a new alert is generated
        pass

    def _on_metrics(self, metrics: Dict[str, Any]):
        """Handle new metrics"""
        # This will be called when new metrics are collected
        pass

    def _update_display(self):
        """Update monitoring display"""
        if not self.monitor:
            return

        dashboard_data = self.monitor.get_dashboard_data()

        # Update metrics
        metrics = dashboard_data.get("metrics", {})
        self.metrics_table.setRowCount(len(metrics))
        row = 0
        for key, value in metrics.items():
            if key != "timestamp":
                self.metrics_table.setItem(row, 0, QTableWidgetItem(str(key)))
                self.metrics_table.setItem(row, 1, QTableWidgetItem(str(value)))
                row += 1

        # Update alerts
        alerts = dashboard_data.get("alerts", [])
        self.alerts_table.setRowCount(len(alerts))
        for i, alert in enumerate(alerts):
            self.alerts_table.setItem(
                i, 0, QTableWidgetItem(alert.get("timestamp", ""))
            )
            self.alerts_table.setItem(i, 1, QTableWidgetItem(alert.get("severity", "")))
            self.alerts_table.setItem(i, 2, QTableWidgetItem(alert.get("title", "")))
            self.alerts_table.setItem(i, 3, QTableWidgetItem(alert.get("message", "")))

        # Update health
        health = dashboard_data.get("health", {})
        checks = health.get("checks", {})
        self.health_table.setRowCount(len(checks))
        row = 0
        for check_name, check_data in checks.items():
            self.health_table.setItem(row, 0, QTableWidgetItem(check_name))
            status = check_data.get("status", "unknown")
            self.health_table.setItem(row, 1, QTableWidgetItem(status))
            row += 1

        # Update performance summary
        if self.performance_analyzer:
            stats = self.performance_analyzer.get_query_statistics()
            self.performance_text.setPlainText(
                f"Query Performance Statistics:\n"
                f"Total Queries: {stats.get('totalQueries', 0)}\n"
                f"Average Execution Time: {stats.get('averageExecutionTime', 0):.2f}ms\n"
                f"Slow Queries: {stats.get('slowQueries', 0)}\n"
                f"Error Queries: {stats.get('errorQueries', 0)}\n"
            )

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        self.connection_combo.clear()
        self.connection_combo.addItem(
            self.i18n.translate("monitoring.select_connection")
        )
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
