"""
Real-time monitoring dashboard widget
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
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
from ..config import DEFAULT_ALERT_CHANNELS, DEFAULT_ALERT_THRESHOLDS
from ..db.base import ConnectionConfig
from ..db.factory import DatabaseConnectionFactory
from ..db.session import ensure_tunnel_for_connection
from ..i18n.manager import get_i18n_manager
from ..monitoring import Alert, AlertSeverity, DatabaseMonitor, NotificationDispatcher
from ..monitoring.notifications import resolve_email_config, validate_email_config
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore
from .jobs import JobRunner
from .utils import (
    apply_glassmorphism,
    apply_page_layout,
    configure_dense_table,
    make_page_header,
)

_THRESHOLD_META: List[Tuple[str, str, float, float, float]] = [
    # metric_key, label_key_suffix, min, max, step
    ("connection_count", "connection_count", 1, 100000, 1),
    ("query_time", "query_time", 1, 600000, 10),
    ("cache_hit_ratio", "cache_hit_ratio", 0, 100, 0.5),
    ("disk_usage", "disk_usage", 1, 100, 0.5),
]

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


_GROUP_START = "monitor-start"
_GROUP_POLL = "monitor-poll"


class MonitoringWidget(QWidget):
    """Real-time monitoring widget.

    Tunnel setup, connection checkout and every poll run on worker threads
    (``JobRunner``); the Qt timer only schedules them and the GUI thread only
    renders results, so monitoring never freezes the window and runs alongside
    Create / Refresh / Verify backup jobs.
    """

    # Alerts are raised inside the poll worker thread; marshal to the GUI thread.
    alert_raised = pyqtSignal(object)

    def __init__(self, connections):
        super().__init__()
        self._jobs = JobRunner(self)
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.secure_store = SecureStore()
        self.current_connection = None
        self.monitor: Optional[DatabaseMonitor] = None
        self._db = None
        self._monitoring_tunnel_id: Optional[str] = None
        self.performance_analyzer = None
        self.index_optimizer = None
        self.growth_predictor = None
        self.capacity_planner = None
        self.notification_dispatcher = NotificationDispatcher()
        self._tray = None
        self._can_read = True
        self._can_write = True
        self._email_ready = False
        self._threshold_spins: Dict[str, Dict[str, QDoubleSpinBox]] = {}
        self.setObjectName("glassmorphism")
        self.init_ui()
        self._load_alert_prefs()
        self.alert_raised.connect(self._handle_alert)
        apply_glassmorphism(self)
        self.apply_rbac()

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        apply_page_layout(layout)
        t = self.i18n.translate

        layout.addWidget(
            make_page_header(
                t("tabs.monitoring"),
                t(
                    "monitoring.page_subtitle",
                    default="Live health, alerts, thresholds, and notification channels",
                ),
            )
        )

        connection_layout = QHBoxLayout()
        connection_layout.setSpacing(8)
        connection_layout.addWidget(QLabel(f"{t('monitoring.connection')}"))
        self.connection_combo = QComboBox()
        self.connection_combo.addItem(t("monitoring.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        self.connection_combo.currentIndexChanged.connect(self._on_connection_changed)
        connection_layout.addWidget(self.connection_combo)

        self.start_button = QPushButton(t("monitoring.start_monitoring"))
        self.start_button.setObjectName("PrimaryButton")
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
        configure_dense_table(self.metrics_table)
        metrics_layout.addWidget(self.metrics_table, 1)
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
        configure_dense_table(self.alerts_table)
        alerts_layout.addWidget(self.alerts_table, 1)
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
        configure_dense_table(self.health_table)
        health_layout.addWidget(self.health_table)
        tabs.addTab(health_widget, t("monitoring.health"))

        thresholds_widget = QWidget()
        thresholds_layout = QVBoxLayout(thresholds_widget)
        self.thresholds_hint = QLabel(
            t(
                "monitoring.thresholds_hint",
                default="Edit warning/critical thresholds. Saved encrypted via SecureStore.",
            )
        )
        self.thresholds_hint.setWordWrap(True)
        thresholds_layout.addWidget(self.thresholds_hint)

        form = QFormLayout()
        self._threshold_spins = {}
        for metric, label_key, vmin, vmax, step in _THRESHOLD_META:
            row = QHBoxLayout()
            warn_spin = QDoubleSpinBox()
            warn_spin.setRange(vmin, vmax)
            warn_spin.setSingleStep(step)
            warn_spin.setDecimals(1 if step < 1 else 0)
            crit_spin = QDoubleSpinBox()
            crit_spin.setRange(vmin, vmax)
            crit_spin.setSingleStep(step)
            crit_spin.setDecimals(1 if step < 1 else 0)
            row.addWidget(QLabel(t("monitoring.warning", default="Warning")))
            row.addWidget(warn_spin)
            row.addWidget(QLabel(t("monitoring.critical", default="Critical")))
            row.addWidget(crit_spin)
            form.addRow(
                t(f"monitoring.threshold_{label_key}", default=metric.replace("_", " ").title()),
                row,
            )
            self._threshold_spins[metric] = {"warning": warn_spin, "critical": crit_spin}
        thresholds_layout.addLayout(form)

        threshold_actions = QHBoxLayout()
        self.save_thresholds_button = QPushButton(
            t("monitoring.save_thresholds", default="Save Thresholds")
        )
        self.save_thresholds_button.clicked.connect(self._save_thresholds)
        threshold_actions.addWidget(self.save_thresholds_button)
        self.reset_thresholds_button = QPushButton(
            t("monitoring.reset_thresholds", default="Reset Defaults")
        )
        self.reset_thresholds_button.clicked.connect(self._reset_thresholds)
        threshold_actions.addWidget(self.reset_thresholds_button)
        threshold_actions.addStretch()
        thresholds_layout.addLayout(threshold_actions)
        thresholds_layout.addStretch()
        tabs.addTab(
            thresholds_widget, t("monitoring.thresholds", default="Thresholds")
        )

        channels_widget = QWidget()
        channels_layout = QVBoxLayout(channels_widget)
        channels_group = QGroupBox(
            t("monitoring.notification_channels", default="Notification channels")
        )
        channels_form = QVBoxLayout(channels_group)
        self.desktop_channel_check = QCheckBox(
            t(
                "monitoring.channel_desktop",
                default="Desktop notifications (system tray)",
            )
        )
        self.in_app_channel_check = QCheckBox(
            t("monitoring.channel_in_app", default="In-app notification log")
        )
        self.email_channel_check = QCheckBox(
            t("monitoring.channel_email", default="Email (SMTP, set up in Settings)")
        )
        channels_form.addWidget(self.desktop_channel_check)
        channels_form.addWidget(self.in_app_channel_check)
        channels_form.addWidget(self.email_channel_check)
        channels_layout.addWidget(channels_group)

        channel_actions = QHBoxLayout()
        self.save_channels_button = QPushButton(
            t("monitoring.save_channels", default="Save Channels")
        )
        self.save_channels_button.clicked.connect(self._save_channels)
        channel_actions.addWidget(self.save_channels_button)
        self.clear_notif_button = QPushButton(
            t("monitoring.clear_notification_log", default="Clear Log")
        )
        self.clear_notif_button.clicked.connect(self._clear_notification_log)
        channel_actions.addWidget(self.clear_notif_button)
        channel_actions.addStretch()
        channels_layout.addLayout(channel_actions)

        self.notification_log = QTableWidget()
        self.notification_log.setColumnCount(4)
        self.notification_log.setHorizontalHeaderLabels(
            [
                t("monitoring.alert_time"),
                t("monitoring.severity"),
                t("monitoring.channel", default="Channel"),
                t("monitoring.message"),
            ]
        )
        self.notification_log.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.notification_log.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        channels_layout.addWidget(self.notification_log)
        tabs.addTab(
            channels_widget, t("monitoring.channels", default="Channels")
        )

        layout.addWidget(tabs, 1)

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._poll_now)
        self.update_timer.setInterval(5000)

    def _on_connection_changed(self, index):
        """Handle connection selection change"""
        if index > 0:
            self.current_connection = self.connection_combo.itemData(index)
            self.start_button.setEnabled(self.monitor is None and self._can_read)
        else:
            self.current_connection = None
            self.start_button.setEnabled(False)

    def _load_alert_prefs(self) -> None:
        """Load thresholds and channel toggles from SecureStore into the UI."""
        settings = self.secure_store.get_settings()
        thresholds = settings.get("alert_thresholds") or copy.deepcopy(
            DEFAULT_ALERT_THRESHOLDS
        )
        self._populate_threshold_spins(thresholds)
        channels = settings.get("alert_channels") or copy.deepcopy(
            DEFAULT_ALERT_CHANNELS
        )
        master_on = bool(settings.get("notifications", True))
        self.desktop_channel_check.setChecked(
            master_on and bool(channels.get("desktop", True))
        )
        self.in_app_channel_check.setChecked(
            master_on and bool(channels.get("in_app", True))
        )
        self.refresh_email_channel(
            checked=master_on and bool(channels.get("email", False))
        )
        self.notification_dispatcher.configure(
            {
                "desktop": self.desktop_channel_check.isChecked(),
                "in_app": self.in_app_channel_check.isChecked(),
                "email": self.email_channel_check.isChecked(),
            }
        )

    def refresh_email_channel(self, checked: Optional[bool] = None) -> None:
        """Re-read the SMTP config; the Email channel needs a complete one."""
        t = self.i18n.translate
        cfg = resolve_email_config(self.secure_store.get_settings())
        problems = validate_email_config(cfg)
        self._email_ready = not problems
        self.notification_dispatcher.set_email_config(cfg)
        if checked is None:
            checked = self.email_channel_check.isChecked()
        self.email_channel_check.setChecked(bool(checked) and self._email_ready)
        self.email_channel_check.setToolTip(
            t("monitoring.email_ready", default="SMTP is configured.")
            if self._email_ready
            else t(
                "monitoring.email_not_ready",
                default="Configure SMTP under Settings → Notifications first: {problems}",
                problems="; ".join(problems),
            )
        )
        self.email_channel_check.setEnabled(
            self._email_ready and getattr(self, "_can_write", True)
        )

    def _populate_threshold_spins(
        self, thresholds: Dict[str, Dict[str, float]]
    ) -> None:
        for metric, spins in self._threshold_spins.items():
            levels = thresholds.get(metric) or DEFAULT_ALERT_THRESHOLDS.get(metric, {})
            spins["warning"].setValue(float(levels.get("warning", 0)))
            spins["critical"].setValue(float(levels.get("critical", 0)))

    def _read_threshold_spins(self) -> Dict[str, Dict[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for metric, spins in self._threshold_spins.items():
            result[metric] = {
                "warning": float(spins["warning"].value()),
                "critical": float(spins["critical"].value()),
            }
        return result

    def _apply_thresholds_to_monitor(
        self, thresholds: Dict[str, Dict[str, float]]
    ) -> None:
        if self.monitor:
            self.monitor.alert_manager.apply_thresholds(thresholds)

    def _save_thresholds(self) -> None:
        if not self._require("monitoring:write"):
            return
        t = self.i18n.translate
        thresholds = self._read_threshold_spins()
        # Validate via a temporary AlertManager
        from ..monitoring import AlertManager

        errors = AlertManager(thresholds).validate_thresholds()
        if errors:
            QMessageBox.warning(
                self,
                t("common.error"),
                "\n".join(errors),
            )
            return
        settings = self.secure_store.get_settings()
        settings["alert_thresholds"] = thresholds
        self.secure_store.set_settings(settings)
        self._apply_thresholds_to_monitor(thresholds)
        QMessageBox.information(
            self,
            t("common.success"),
            t(
                "monitoring.thresholds_saved",
                default="Alert thresholds saved.",
            ),
        )

    def _reset_thresholds(self) -> None:
        self._populate_threshold_spins(copy.deepcopy(DEFAULT_ALERT_THRESHOLDS))

    def _save_channels(self) -> None:
        if not self._require("monitoring:write"):
            return
        t = self.i18n.translate
        channels = {
            "desktop": self.desktop_channel_check.isChecked(),
            "in_app": self.in_app_channel_check.isChecked(),
            "email": self.email_channel_check.isChecked(),
        }
        settings = self.secure_store.get_settings()
        settings["alert_channels"] = channels
        # Keep global notifications flag in sync when any channel is on
        settings["notifications"] = any(channels.values())
        self.secure_store.set_settings(settings)
        self.notification_dispatcher.configure(channels)
        QMessageBox.information(
            self,
            t("common.success"),
            t(
                "monitoring.channels_saved",
                default="Notification channels saved.",
            ),
        )

    def _clear_notification_log(self) -> None:
        self.notification_dispatcher.clear_in_app_log()
        self._refresh_notification_log()

    def _refresh_notification_log(self) -> None:
        entries = list(reversed(self.notification_dispatcher.in_app_log[-100:]))
        self.notification_log.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.notification_log.setItem(
                row, 0, QTableWidgetItem(str(entry.get("timestamp", "")))
            )
            sev = str(entry.get("severity", "info")).lower()
            brush = QBrush(_SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["info"]))
            sev_item = QTableWidgetItem(sev.upper())
            chan_item = QTableWidgetItem(str(entry.get("channel", "")))
            msg_item = QTableWidgetItem(
                f"{entry.get('title', '')}: {entry.get('message', '')}"
            )
            for item in (sev_item, chan_item, msg_item):
                item.setForeground(brush)
            self.notification_log.setItem(row, 1, sev_item)
            self.notification_log.setItem(row, 2, chan_item)
            self.notification_log.setItem(row, 3, msg_item)

    def attach_tray(self, tray) -> None:
        """Deliver desktop alerts through the shared application tray icon."""
        self._tray = tray
        self.notification_dispatcher.set_desktop_handler(tray.notify)

    def apply_rbac(self) -> None:
        """Gate monitoring controls: read starts/polls, write edits prefs / acks."""
        auth = get_auth_manager()
        self._can_read = auth.has_permission("monitoring:read")
        self._can_write = auth.has_permission("monitoring:write")
        self.start_button.setEnabled(
            self._can_read and self.current_connection is not None and self.monitor is None
        )
        for widget in (
            self.save_thresholds_button,
            self.reset_thresholds_button,
            self.save_channels_button,
            self.clear_notif_button,
            self.desktop_channel_check,
            self.in_app_channel_check,
        ):
            widget.setEnabled(self._can_write)
        self.email_channel_check.setEnabled(
            self._can_write and getattr(self, "_email_ready", False)
        )
        for spins in self._threshold_spins.values():
            for spin in spins.values():
                spin.setEnabled(self._can_write)
        running = self.monitor is not None
        self.acknowledge_all_button.setEnabled(self._can_write and running)
        self.acknowledge_button.setEnabled(
            self._can_write
            and running
            and bool(self.alerts_table.selectionModel().selectedRows())
        )

    def _require(self, permission: str) -> bool:
        try:
            get_auth_manager().require(permission)
            return True
        except PermissionDenied as exc:
            QMessageBox.warning(
                self,
                self.i18n.translate("auth.denied", default="Access denied"),
                str(exc),
            )
            return False

    def status_summary(self) -> str:
        """One-line monitoring status for the system tray menu."""
        t = self.i18n.translate
        if self.monitor is None or not self.current_connection:
            return ""
        counts = self.monitor.alert_manager.get_counts()
        return t(
            "tray.monitoring_status",
            connection=self.current_connection.get("name", ""),
            alerts=counts.get("total", 0),
        )

    def shutdown(self) -> None:
        """Stop timers and wait briefly for in-flight polls (window close)."""
        self.update_timer.stop()
        self._jobs.wait_all(3000)
        # Let an in-flight alert email finish instead of dropping it on exit.
        self.notification_dispatcher.wait_email_idle(5.0)

    def autostart_if_configured(self) -> bool:
        """Start watching the connection chosen in Settings (monitor-role UX).

        Returns True when a start was requested. Honours RBAC: needs
        ``monitoring:read``; does nothing when monitoring already runs.
        """
        if self.monitor is not None or not self._can_read:
            return False
        wanted = (self.secure_store.get_settings().get("monitoring") or {}).get(
            "autostart_connection_id"
        )
        if not wanted:
            return False
        for index in range(1, self.connection_combo.count()):
            conn = self.connection_combo.itemData(index)
            if conn and conn.get("id") == wanted:
                self.connection_combo.setCurrentIndex(index)
                self._start_monitoring()
                return True
        return False

    def _start_monitoring(self):
        """Start monitoring: tunnel + checkout on a worker, then timer-driven polls."""
        if not self.current_connection or self.monitor is not None:
            return
        if not self._require("monitoring:read"):
            return
        connection = self.current_connection
        t = self.i18n.translate

        def job():
            # Open/reuse SSH tunnel before driver connect (same as Connections test)
            kwargs = ensure_tunnel_for_connection(connection)
            config = ConnectionConfig(**kwargs)
            return asyncio.run(DatabaseConnectionFactory.acquire(config))

        def on_start():
            self.start_button.setEnabled(False)
            self.connection_combo.setEnabled(False)
            self.status_label.setText(
                t("monitoring.status_connecting", default="Connecting…")
            )

        def on_ok(db):
            ssh = connection.get("ssh_config") or {}
            if ssh.get("enabled"):
                self._monitoring_tunnel_id = str(
                    connection.get("id") or connection.get("name") or "session"
                )
            self._db = db
            self.monitor = DatabaseMonitor(db)
            self.monitor.monitoring = True
            # Apply persisted thresholds before the first poll
            self.monitor.alert_manager.apply_thresholds(self._read_threshold_spins())
            self.monitor.alert_manager.add_alert_callback(self._on_alert)
            self.monitor._on_metrics = self._on_metrics
            self.performance_analyzer = QueryPerformanceAnalyzer(db)
            self.index_optimizer = IndexOptimizer(db)
            self.growth_predictor = StorageGrowthPredictor(db)
            self.capacity_planner = CapacityPlanner(db)

            self.stop_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.apply_rbac()
            self._poll_now()
            self.update_timer.start()

        def on_fail(message):
            self._cleanup_monitor()
            self.connection_combo.setEnabled(True)
            self.start_button.setEnabled(
                self._can_read and self.current_connection is not None
            )
            self.status_label.setText(t("monitoring.status_idle"))
            QMessageBox.critical(self, t("common.error"), message)

        if not self._jobs.submit(
            _GROUP_START, job, on_ok, on_fail, on_start=on_start
        ):
            return

    def _stop_monitoring(self):
        """Stop monitoring; the checkout is released after any in-flight poll."""
        self.update_timer.stop()
        db = self._db
        if self.monitor:
            self.monitor.monitoring = False
            self.monitor.metrics_collector.stop_collecting()
        self._cleanup_monitor()
        if db is not None:

            def release():
                asyncio.run(DatabaseConnectionFactory.release(db))

            # Same group as polls: runs once the current poll (if any) finished.
            self._jobs.submit(
                _GROUP_POLL, release, lambda _r: None, lambda _m: None, queue=True
            )
        self.start_button.setEnabled(
            self._can_read and self.current_connection is not None
        )
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
        # Leave shared tunnels open for Dashboard / Connections reuse;
        # only clear the local tracking id.
        self._monitoring_tunnel_id = None

    def _poll_now(self):
        """Run one real poll cycle on a worker thread, then refresh the tables."""
        monitor = self.monitor
        if monitor is None:
            return

        def job():
            asyncio.run(monitor.poll_once())

        def on_ok(_result):
            if self.monitor is monitor:
                self._update_display()
                self._refresh_notification_log()

        def on_fail(message):
            if self.monitor is monitor:
                self.status_label.setText(
                    self.i18n.translate("monitoring.poll_failed", error=message)
                )

        # A poll still running (slow SSH link) simply skips this timer tick.
        self._jobs.submit(_GROUP_POLL, job, on_ok, on_fail)

    def _on_alert(self, alert: Alert):
        """AlertManager callback (poll worker thread) - hand off to the GUI thread."""
        self.alert_raised.emit(alert)

    def _handle_alert(self, alert: Alert):
        """Fire notification channels on the GUI thread."""
        self.notification_dispatcher.notify(alert)
        self._refresh_notification_log()

    def _on_metrics(self, metrics: Dict[str, Any]):
        """Handle new metrics callback."""
        _ = metrics

    def _on_alert_selection_changed(self):
        has_selection = bool(self.alerts_table.selectionModel().selectedRows())
        self.acknowledge_button.setEnabled(
            bool(self.monitor) and has_selection and self._can_write
        )

    def _acknowledge_selected(self):
        if not self.monitor or not self._require("monitoring:write"):
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
        if not self.monitor or not self._require("monitoring:write"):
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
            label = self.i18n.translate(
                f"monitoring.metric_{key}", default=_METRIC_LABELS.get(key, key)
            )
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
            sev_item = QTableWidgetItem(
                self.i18n.translate(
                    f"monitoring.severity_{severity}", default=severity.upper()
                )
            )
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
            name_item = QTableWidgetItem(
                self.i18n.translate(
                    f"monitoring.check_{check_name}",
                    default=check_name.replace("_", " ").title(),
                )
            )
            status_item = QTableWidgetItem(
                self.i18n.translate(f"monitoring.status_{status}", default=status)
            )
            detail_item = QTableWidgetItem(detail)
            for item in (name_item, status_item, detail_item):
                item.setForeground(brush)
            self.health_table.setItem(row, 0, name_item)
            self.health_table.setItem(row, 1, status_item)
            self.health_table.setItem(row, 2, detail_item)

        if self.performance_analyzer:
            stats = self.performance_analyzer.get_query_statistics()
            summary = self.monitor.get_performance_summary()
            tr = self.i18n.translate
            self.performance_text.setPlainText(
                "\n".join(
                    [
                        tr("monitoring.perf_stats_title"),
                        tr("monitoring.perf_total_queries", value=stats.get("totalQueries", 0)),
                        tr(
                            "monitoring.perf_avg_time",
                            value=f"{stats.get('averageExecutionTime', 0):.2f}",
                        ),
                        tr("monitoring.perf_slow_queries", value=stats.get("slowQueries", 0)),
                        tr("monitoring.perf_error_queries", value=stats.get("errorQueries", 0)),
                        "",
                        tr("monitoring.perf_summary_title"),
                        tr(
                            "monitoring.perf_avg_connections",
                            value=f"{summary.get('averageConnections', 0):.2f}",
                        ),
                        tr("monitoring.perf_max_connections", value=summary.get("maxConnections", 0)),
                        tr(
                            "monitoring.perf_avg_cache",
                            value=f"{summary.get('averageCacheHitRatio', 0):.2f}",
                        ),
                        tr("monitoring.perf_data_points", value=summary.get("dataPoints", 0)),
                    ]
                )
                + "\n"
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
