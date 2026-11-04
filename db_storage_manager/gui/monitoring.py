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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
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
from ..monitoring.notifications import (
    EMAIL_SECURITY_MODES,
    resolve_email_config,
    resolve_discord_config,
    resolve_slack_config,
    resolve_telegram_config,
    resolve_webhook_config,
    validate_email_config,
    validate_webhook_config,
)
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore
from .icons import set_icon_only
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
    "queryTime": "Slowest active query (ms)",
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
_GROUP_MULTI = "multi-watch"


def _execute_installed(plugin_id: str, **kwargs: Any) -> Any:
    """Run an installed, enabled plugin. ``None`` when it is not loaded."""
    from ..plugins.marketplace import LocalPluginMarketplace

    market = LocalPluginMarketplace()
    market.load_into_manager(only_enabled=True)
    return market.manager.execute_plugin(plugin_id, **kwargs)


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
        self._conn_email_ready = False
        self._conn_email_password_set = False
        self._multi_ready = False
        self._multi_status_by_id: Dict[str, str] = {}
        self._plugin_snapshot: Optional[Tuple[Any, ...]] = None
        self._threshold_spins: Dict[str, Dict[str, QDoubleSpinBox]] = {}
        self.setObjectName("glassmorphism")
        self.init_ui()
        self._load_alert_prefs()
        self._reload_plugin_forms()
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
        set_icon_only(
            self.refresh_button,
            "refresh",
            t("monitoring.refresh_now").replace("&", ""),
        )
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
        self.webhook_channel_check = QCheckBox(
            t("monitoring.channel_webhook", default="Webhook (set up in Settings)")
        )
        self.slack_channel_check = QCheckBox(
            t("monitoring.channel_slack", default="Slack (set up in Settings)")
        )
        self.discord_channel_check = QCheckBox(
            t("monitoring.channel_discord", default="Discord (set up in Settings)")
        )
        self.telegram_channel_check = QCheckBox(
            t("monitoring.channel_telegram", default="Telegram (set up in Settings)")
        )
        channels_form.addWidget(self.desktop_channel_check)
        channels_form.addWidget(self.in_app_channel_check)
        channels_form.addWidget(self.email_channel_check)
        channels_form.addWidget(self.webhook_channel_check)
        channels_form.addWidget(self.slack_channel_check)
        channels_form.addWidget(self.discord_channel_check)
        channels_form.addWidget(self.telegram_channel_check)
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

        self._build_connection_email_group(t)
        channels_layout.addWidget(self.conn_email_group)
        self._build_multi_watch_group(t)
        channels_layout.addWidget(self.multi_group)

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

        # The extra health check is its own job. It does not wait for Start
        # on the connection combo, and it never runs on this thread.
        self.multi_timer = QTimer(self)
        self.multi_timer.timeout.connect(self._schedule_multi_watch)
        self.multi_timer.setInterval(60_000)
        self.multi_timer.start()

    def _build_connection_email_group(self, t) -> None:
        """Per-connection SMTP. The workstation-wide Settings profile is separate."""
        self.conn_email_group = QGroupBox(
            t("monitoring.conn_email_group", default="Connection email alerts")
        )
        form = QFormLayout(self.conn_email_group)
        self.conn_email_status = QLabel(
            t(
                "monitoring.conn_email_hint",
                default=(
                    "Opt-in SMTP for one saved connection. Separate from the "
                    "workstation-wide profile. The password stays in SecureStore "
                    "and nothing is sent until this plugin is installed and the "
                    "profile is enabled."
                ),
            )
        )
        self.conn_email_status.setWordWrap(True)
        form.addRow(self.conn_email_status)
        self.conn_email_combo = QComboBox()
        self.conn_email_combo.currentIndexChanged.connect(
            lambda _index: self._fill_connection_email()
        )
        form.addRow(
            t("monitoring.connection", default="Connection"), self.conn_email_combo
        )
        self.conn_email_enabled = QCheckBox(
            t(
                "monitoring.conn_email_enabled",
                default="Send email for this connection",
            )
        )
        form.addRow(self.conn_email_enabled)
        self.conn_email_host = QLineEdit()
        self.conn_email_host.setPlaceholderText("smtp.example.com")
        form.addRow(
            t("settings.email_host", default="SMTP host"), self.conn_email_host
        )
        self.conn_email_port = QSpinBox()
        self.conn_email_port.setRange(1, 65535)
        self.conn_email_port.setValue(587)
        form.addRow(t("settings.email_port", default="Port"), self.conn_email_port)
        self.conn_email_security = QComboBox()
        for mode in EMAIL_SECURITY_MODES:
            self.conn_email_security.addItem(mode.upper(), mode)
        form.addRow(
            t("settings.email_security", default="Security"),
            self.conn_email_security,
        )
        self.conn_email_user = QLineEdit()
        form.addRow(
            t("settings.email_username", default="Username"), self.conn_email_user
        )
        self.conn_email_password = QLineEdit()
        self.conn_email_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(
            t("settings.email_password", default="Password"),
            self.conn_email_password,
        )
        self.conn_email_sender = QLineEdit()
        self.conn_email_sender.setPlaceholderText("alerts@example.com")
        form.addRow(
            t("settings.email_sender", default="From address"),
            self.conn_email_sender,
        )
        self.conn_email_recipients = QLineEdit()
        self.conn_email_recipients.setPlaceholderText(
            "oncall@example.com, dba@example.com"
        )
        form.addRow(
            t(
                "settings.email_recipients",
                default="Recipients (comma-separated)",
            ),
            self.conn_email_recipients,
        )
        self.conn_email_severity = QComboBox()
        self.conn_email_severity.addItem(
            t("settings.severity_critical", default="Critical only"), "critical"
        )
        self.conn_email_severity.addItem(
            t("settings.severity_warning", default="Warning and critical"),
            "warning",
        )
        form.addRow(
            t("settings.email_min_severity", default="Minimum severity"),
            self.conn_email_severity,
        )
        self.conn_email_cooldown = QSpinBox()
        self.conn_email_cooldown.setRange(1, 24 * 60)
        self.conn_email_cooldown.setValue(30)
        self.conn_email_cooldown.setSuffix(
            " " + t("settings.minutes_suffix", default="min")
        )
        form.addRow(
            t("settings.email_cooldown", default="Repeat cooldown"),
            self.conn_email_cooldown,
        )
        self.conn_email_save = QPushButton(
            t("monitoring.conn_email_save", default="Save connection email")
        )
        self.conn_email_save.clicked.connect(self._save_connection_email)
        form.addRow(self.conn_email_save)

    def _build_multi_watch_group(self, t) -> None:
        self.multi_group = QGroupBox(
            t("monitoring.multi_group", default="Multi-connection monitor")
        )
        layout = QVBoxLayout(self.multi_group)
        self.multi_status = QLabel(
            t(
                "monitoring.multi_hint",
                default=(
                    "Health-check the connections you opt in. Polls at least "
                    "60 seconds apart and uses only the stored credentials."
                ),
            )
        )
        self.multi_status.setWordWrap(True)
        layout.addWidget(self.multi_status)
        self.multi_list = QListWidget()
        self.multi_list.setMaximumHeight(120)
        layout.addWidget(self.multi_list)
        self.multi_save = QPushButton(
            t("monitoring.multi_save", default="Save watched connections")
        )
        self.multi_save.clicked.connect(self._save_multi_watch)
        layout.addWidget(self.multi_save)
        self.multi_results = QTableWidget()
        self.multi_results.setColumnCount(3)
        self.multi_results.setHorizontalHeaderLabels(
            [
                t("monitoring.connection", default="Connection"),
                t("monitoring.status", default="Status"),
                t("monitoring.detail", default="Detail"),
            ]
        )
        self.multi_results.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.multi_results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.multi_results.setMaximumHeight(140)
        layout.addWidget(self.multi_results)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        from ..monitoring.connection_email import plugin_ready as email_ready
        from ..monitoring.multi_watch import plugin_ready as watch_ready

        snapshot = (
            email_ready(),
            watch_ready(),
            tuple(str(conn.get("id") or "") for conn in self.connections),
        )
        if snapshot != self._plugin_snapshot:
            self._reload_plugin_forms()
        else:
            self._conn_email_ready = snapshot[0]
            self._multi_ready = snapshot[1]
        self.apply_rbac()

    def _reload_plugin_forms(self) -> None:
        from ..monitoring.connection_email import plugin_ready as email_ready
        from ..monitoring.multi_watch import plugin_ready as watch_ready

        self._plugin_snapshot = (
            email_ready(),
            watch_ready(),
            tuple(str(conn.get("id") or "") for conn in self.connections),
        )
        self._reload_email_combo()
        self._reload_multi_list()

    def _reload_email_combo(self) -> None:
        from ..monitoring.connection_email import plugin_ready

        current = self.conn_email_combo.currentData()
        current_id = current.get("id") if isinstance(current, dict) else None
        self.conn_email_combo.blockSignals(True)
        self.conn_email_combo.clear()
        selected = 0
        for index, conn in enumerate(self.connections):
            self.conn_email_combo.addItem(
                str(conn.get("name") or conn.get("id") or ""), conn
            )
            if current_id and conn.get("id") == current_id:
                selected = index
        if self.conn_email_combo.count():
            self.conn_email_combo.setCurrentIndex(selected)
        self.conn_email_combo.blockSignals(False)
        self._conn_email_ready = plugin_ready()
        self._fill_connection_email()

    def _fill_connection_email(self) -> None:
        from ..monitoring.connection_email import list_public_profiles

        t = self.i18n.translate
        conn = self.conn_email_combo.currentData()
        connection_id = (
            str(conn.get("id")) if isinstance(conn, dict) and conn.get("id") else ""
        )
        profile = list_public_profiles().get(connection_id) or {}
        self.conn_email_enabled.setChecked(bool(profile.get("enabled")))
        self.conn_email_host.setText(str(profile.get("host") or ""))
        try:
            port = int(profile.get("port") or 587)
        except (TypeError, ValueError):
            port = 587
        self.conn_email_port.setValue(port if 1 <= port <= 65535 else 587)
        security = self.conn_email_security.findData(profile.get("security") or "starttls")
        self.conn_email_security.setCurrentIndex(max(security, 0))
        self.conn_email_user.setText(str(profile.get("username") or ""))
        self.conn_email_password.clear()
        self._conn_email_password_set = bool(profile.get("password_set"))
        self.conn_email_password.setPlaceholderText(
            t(
                "settings.email_password_set",
                default="Stored — leave blank to keep",
            )
            if self._conn_email_password_set
            else ""
        )
        self.conn_email_sender.setText(str(profile.get("sender") or ""))
        self.conn_email_recipients.setText(
            ", ".join(str(item) for item in (profile.get("recipients") or []))
        )
        severity = self.conn_email_severity.findData(
            profile.get("min_severity") or "critical"
        )
        self.conn_email_severity.setCurrentIndex(max(severity, 0))
        try:
            cooldown = int(profile.get("cooldown_minutes") or 30)
        except (TypeError, ValueError):
            cooldown = 30
        self.conn_email_cooldown.setValue(min(24 * 60, max(1, cooldown)))
        if self._conn_email_ready:
            self.conn_email_status.setText(
                t(
                    "monitoring.conn_email_hint",
                    default=(
                        "Opt-in SMTP for one saved connection. Separate from the "
                        "workstation-wide profile. The password stays in SecureStore "
                        "and nothing is sent until this plugin is installed and the "
                        "profile is enabled."
                    ),
                )
            )
        else:
            self.conn_email_status.setText(
                t(
                    "monitoring.conn_email_off",
                    default=(
                        "not_available: install and enable connection-email-alerts "
                        "on the Plugins page."
                    ),
                )
            )

    def _save_connection_email(self) -> None:
        if not self._require("settings:write"):
            return
        t = self.i18n.translate
        conn = self.conn_email_combo.currentData()
        if not isinstance(conn, dict) or not conn.get("id"):
            self.conn_email_status.setText(
                t(
                    "monitoring.conn_email_off",
                    default=(
                        "not_available: install and enable connection-email-alerts "
                        "on the Plugins page."
                    ),
                )
            )
            return
        recipients = [
            part.strip()
            for part in self.conn_email_recipients.text().split(",")
            if part.strip()
        ]
        profile: Dict[str, Any] = {
            "enabled": self.conn_email_enabled.isChecked(),
            "host": self.conn_email_host.text().strip(),
            "port": int(self.conn_email_port.value()),
            "security": self.conn_email_security.currentData(),
            "username": self.conn_email_user.text().strip(),
            "sender": self.conn_email_sender.text().strip(),
            "recipients": recipients,
            "min_severity": self.conn_email_severity.currentData(),
            "cooldown_minutes": int(self.conn_email_cooldown.value()),
        }
        password = self.conn_email_password.text()
        if password:
            profile["password"] = password
        if profile["enabled"]:
            check = dict(profile)
            if not password and self._conn_email_password_set:
                check["password"] = "stored"
            problems = validate_email_config(check)
            if problems:
                self.conn_email_status.setText("; ".join(problems))
                return
        try:
            result = _execute_installed(
                "connection-email-alerts",
                connection_id=str(conn["id"]),
                profile=profile,
            )
        except PermissionDenied as exc:
            QMessageBox.warning(
                self,
                t("auth.denied", default="Access denied"),
                str(exc),
            )
            return
        if not isinstance(result, dict) or result.get("status") != "saved":
            reason = result.get("reason") if isinstance(result, dict) else None
            self.conn_email_status.setText(
                str(
                    reason
                    or t(
                        "monitoring.conn_email_off",
                        default=(
                            "not_available: install and enable "
                            "connection-email-alerts on the Plugins page."
                        ),
                    )
                )
            )
            return
        self.conn_email_password.clear()
        self._conn_email_password_set = True
        self.conn_email_password.setPlaceholderText(
            t(
                "settings.email_password_set",
                default="Stored — leave blank to keep",
            )
        )
        self.conn_email_status.setText(
            t(
                "monitoring.conn_email_saved",
                default="Saved SMTP for {name}. The password is stored and is not shown again.",
                name=str(conn.get("name") or conn["id"]),
            )
        )

    def _reload_multi_list(self) -> None:
        from ..monitoring.multi_watch import configured, plugin_ready

        t = self.i18n.translate
        self._multi_ready = plugin_ready()
        chosen = set(configured().get("connection_ids") or [])
        self.multi_list.clear()
        for conn in self.connections:
            connection_id = str(conn.get("id") or "")
            if not connection_id:
                continue
            item = QListWidgetItem(str(conn.get("name") or connection_id))
            item.setData(Qt.ItemDataRole.UserRole, connection_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if connection_id in chosen
                else Qt.CheckState.Unchecked
            )
            self.multi_list.addItem(item)
        if not self._multi_ready:
            self.multi_status.setText(
                t(
                    "monitoring.multi_off",
                    default=(
                        "not_available: install and enable multi-connection-monitor "
                        "on the Plugins page."
                    ),
                )
            )
        elif not chosen:
            self.multi_status.setText(
                t(
                    "monitoring.multi_none",
                    default="No connection is opted in.",
                )
            )
        else:
            self.multi_status.setText(
                t(
                    "monitoring.multi_hint",
                    default=(
                        "Health-check the connections you opt in. Polls at least "
                        "60 seconds apart and uses only the stored credentials."
                    ),
                )
            )

    def _save_multi_watch(self) -> None:
        if not self._require("settings:write"):
            return
        ids: List[str] = []
        for index in range(self.multi_list.count()):
            item = self.multi_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(str(item.data(Qt.ItemDataRole.UserRole)))

        def job():
            result = _execute_installed(
                "multi-connection-monitor", connection_ids=ids
            )
            if result is None:
                return {
                    "status": "not_available",
                    "reason": "multi-connection-monitor is not installed or not enabled.",
                    "connections": [],
                }
            return result

        if not self._jobs.submit(
            _GROUP_MULTI, job, self._show_multi_report, self._on_multi_fail
        ):
            self.multi_status.setText(
                self.i18n.translate(
                    "monitoring.status_connecting", default="Connecting…"
                )
            )

    def _schedule_multi_watch(self) -> None:
        if not self._can_read:
            return

        def job():
            from ..monitoring.multi_watch import watch_if_installed

            return watch_if_installed()

        self._jobs.submit(
            _GROUP_MULTI, job, self._show_multi_report, lambda _message: None
        )

    def _on_multi_fail(self, message: str) -> None:
        self.multi_status.setText(message)

    def _show_multi_report(self, report: Any) -> None:
        if not isinstance(report, dict):
            return
        if report.get("reason") == "Rate limited.":
            return
        t = self.i18n.translate
        rows = report.get("connections") or []
        if not isinstance(rows, list):
            rows = []
        self.multi_results.setRowCount(len(rows))
        seen: Dict[str, str] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            connection_id = str(row.get("id") or "")
            status = str(row.get("status") or "not_available")
            summary = str(row.get("summary") or "")
            seen[connection_id] = status
            self.multi_results.setItem(index, 0, QTableWidgetItem(connection_id))
            self.multi_results.setItem(index, 1, QTableWidgetItem(status))
            self.multi_results.setItem(index, 2, QTableWidgetItem(summary))
            if status not in {"degraded", "unhealthy"}:
                continue
            if self._multi_status_by_id.get(connection_id) == status:
                continue
            severity = (
                AlertSeverity.CRITICAL
                if status == "unhealthy"
                else AlertSeverity.WARNING
            )
            self.notification_dispatcher.notify(
                Alert(
                    "Connection health",
                    summary or status,
                    severity,
                    "multi-connection-monitor",
                    connection_id,
                )
            )
        self._multi_status_by_id = seen
        reason = str(report.get("reason") or "")
        if reason:
            self.multi_status.setText(reason)
        elif rows:
            self.multi_status.setText(
                t(
                    "monitoring.multi_hint",
                    default=(
                        "Health-check the connections you opt in. Polls at least "
                        "60 seconds apart and uses only the stored credentials."
                    ),
                )
            )
        else:
            self.multi_status.setText(
                t("monitoring.multi_none", default="No connection is opted in.")
            )
        self._refresh_notification_log()

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
        self.refresh_http_channels(
            webhook=master_on and bool(channels.get("webhook", False)),
            slack=master_on and bool(channels.get("slack", False)),
            discord=master_on and bool(channels.get("discord", False)),
            telegram=master_on and bool(channels.get("telegram", False)),
        )
        self.notification_dispatcher.configure(self._channel_flags())

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

    def _channel_flags(self) -> Dict[str, bool]:
        return {
            "desktop": self.desktop_channel_check.isChecked(),
            "in_app": self.in_app_channel_check.isChecked(),
            "email": self.email_channel_check.isChecked(),
            "webhook": self.webhook_channel_check.isChecked(),
            "slack": self.slack_channel_check.isChecked(),
            "discord": self.discord_channel_check.isChecked(),
            "telegram": self.telegram_channel_check.isChecked(),
        }

    def refresh_http_channels(
        self,
        webhook: Optional[bool] = None,
        slack: Optional[bool] = None,
        discord: Optional[bool] = None,
        telegram: Optional[bool] = None,
    ) -> None:
        """Enable HTTP channels only when the saved secret passes the same rules."""
        t = self.i18n.translate
        settings = self.secure_store.get_settings()
        webhook_cfg = resolve_webhook_config(settings)
        slack_cfg = resolve_slack_config(settings)
        discord_cfg = resolve_discord_config(settings)
        telegram_cfg = resolve_telegram_config(settings)
        webhook_problems = validate_webhook_config(webhook_cfg, kind="webhook")
        slack_problems = validate_webhook_config(slack_cfg, kind="slack")
        discord_problems = validate_webhook_config(discord_cfg, kind="discord")
        telegram_problems = validate_webhook_config(telegram_cfg, kind="telegram")
        self._webhook_ready = not webhook_problems
        self._slack_ready = not slack_problems
        self._discord_ready = not discord_problems
        self._telegram_ready = not telegram_problems
        self.notification_dispatcher.set_webhook_config(webhook_cfg)
        self.notification_dispatcher.set_slack_config(slack_cfg)
        self.notification_dispatcher.set_discord_config(discord_cfg)
        self.notification_dispatcher.set_telegram_config(telegram_cfg)
        if webhook is None:
            webhook = self.webhook_channel_check.isChecked()
        if slack is None:
            slack = self.slack_channel_check.isChecked()
        if discord is None:
            discord = self.discord_channel_check.isChecked()
        if telegram is None:
            telegram = self.telegram_channel_check.isChecked()
        self.webhook_channel_check.setChecked(bool(webhook) and self._webhook_ready)
        self.slack_channel_check.setChecked(bool(slack) and self._slack_ready)
        self.discord_channel_check.setChecked(bool(discord) and self._discord_ready)
        self.telegram_channel_check.setChecked(bool(telegram) and self._telegram_ready)
        self.webhook_channel_check.setToolTip(
            t("monitoring.webhook_ready", default="Webhook URL is configured.")
            if self._webhook_ready
            else t(
                "monitoring.webhook_not_ready",
                default="Configure the webhook under Settings → Notifications first: {problems}",
                problems="; ".join(webhook_problems),
            )
        )
        self.slack_channel_check.setToolTip(
            t("monitoring.slack_ready", default="Slack webhook is configured.")
            if self._slack_ready
            else t(
                "monitoring.slack_not_ready",
                default="Configure the Slack webhook under Settings → Notifications first: {problems}",
                problems="; ".join(slack_problems),
            )
        )
        self.discord_channel_check.setToolTip(
            t("monitoring.discord_ready", default="Discord webhook is configured.")
            if self._discord_ready
            else t(
                "monitoring.discord_not_ready",
                default="Configure the Discord webhook under Settings → Notifications first: {problems}",
                problems="; ".join(discord_problems),
            )
        )
        self.telegram_channel_check.setToolTip(
            t("monitoring.telegram_ready", default="Telegram bot is configured.")
            if self._telegram_ready
            else t(
                "monitoring.telegram_not_ready",
                default="Configure the Telegram bot under Settings → Notifications first: {problems}",
                problems="; ".join(telegram_problems),
            )
        )
        can_write = getattr(self, "_can_write", True)
        self.webhook_channel_check.setEnabled(self._webhook_ready and can_write)
        self.slack_channel_check.setEnabled(self._slack_ready and can_write)
        self.discord_channel_check.setEnabled(self._discord_ready and can_write)
        self.telegram_channel_check.setEnabled(self._telegram_ready and can_write)

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
        channels = self._channel_flags()
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
        self.webhook_channel_check.setEnabled(
            self._can_write and getattr(self, "_webhook_ready", False)
        )
        self.slack_channel_check.setEnabled(
            self._can_write and getattr(self, "_slack_ready", False)
        )
        self.discord_channel_check.setEnabled(
            self._can_write and getattr(self, "_discord_ready", False)
        )
        self.telegram_channel_check.setEnabled(
            self._can_write and getattr(self, "_telegram_ready", False)
        )
        can_settings = auth.has_permission("settings:write")
        email_on = can_settings and self._conn_email_ready
        for widget in (
            self.conn_email_combo,
            self.conn_email_enabled,
            self.conn_email_host,
            self.conn_email_port,
            self.conn_email_security,
            self.conn_email_user,
            self.conn_email_password,
            self.conn_email_sender,
            self.conn_email_recipients,
            self.conn_email_severity,
            self.conn_email_cooldown,
            self.conn_email_save,
        ):
            widget.setEnabled(email_on)
        watch_on = can_settings and self._multi_ready
        self.multi_list.setEnabled(watch_on)
        self.multi_save.setEnabled(watch_on)
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
        self.multi_timer.stop()
        self._jobs.wait_all(3000)
        # Let an in-flight alert email finish instead of dropping it on exit.
        self.notification_dispatcher.wait_email_idle(5.0)

    def autostart_if_configured(self) -> bool:
        """Start watching the connection chosen in Settings (monitor-role UX).

        Returns True when a start was requested. Honours RBAC: needs
        ``monitoring:read``; does nothing when monitoring already runs.
        When ``multi-connection-monitor`` is installed, also polls the
        connections that plugin was opted into. That call is a no-op until
        the plugin is installed.
        """
        if not self._can_read:
            return False
        started = False
        if self.monitor is None:
            wanted = (self.secure_store.get_settings().get("monitoring") or {}).get(
                "autostart_connection_id"
            )
            if wanted:
                for index in range(1, self.connection_combo.count()):
                    conn = self.connection_combo.itemData(index)
                    if conn and conn.get("id") == wanted:
                        self.connection_combo.setCurrentIndex(index)
                        self._start_monitoring()
                        started = True
                        break
        # Off the GUI thread. A no-op until the plugin is installed and a
        # connection was opted in on Monitoring → Channels.
        self._schedule_multi_watch()
        return started

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
            try:
                from ..monitoring.multi_watch import watch_if_installed

                return watch_if_installed()
            except Exception:
                return None

        def on_ok(result):
            if self.monitor is monitor:
                self._update_display()
                self._refresh_notification_log()
            self._show_multi_report(result)

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
        connection = self.current_connection or {}
        if connection.get("id") and not getattr(alert, "connection_id", None):
            alert.connection_id = str(connection["id"])
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
        self._reload_plugin_forms()
        self.apply_rbac()
