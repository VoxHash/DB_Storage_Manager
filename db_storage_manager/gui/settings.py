"""
Settings widget — tabbed: General, Backups & Adapters, Notifications,
Users & RBAC, Updates.
"""

import importlib.util
from typing import Any, Dict, List

from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..backups.protondrive import configuration_status as proton_drive_status
from ..backups.s3 import configuration_status as s3_status
from ..config import DEFAULT_SETTINGS
from ..experimental import ENV_VAR as EXPERIMENTAL_ENV_VAR
from ..experimental import env_forces_experimental
from ..i18n.languages import SUPPORTED_LANGUAGES
from ..i18n.manager import get_i18n_manager
from ..monitoring.notifications import (
    EMAIL_SECURITY_MODES,
    resolve_discord_config,
    resolve_email_config,
    resolve_slack_config,
    resolve_telegram_config,
    resolve_webhook_config,
    send_test_email,
    validate_email_config,
)
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore
from ..themes.manager import get_theme_manager
from ..themes.themes import THEMES
from .icons import themed_icon
from .jobs import JobRunner
from .updates import UpdatesPanel
from .proton_drive_config import open_proton_drive_config
from .s3_config import open_s3_config
from .tray import (
    DEFAULT_NOTIFICATION_SECONDS,
    MAX_NOTIFICATION_SECONDS,
    MIN_NOTIFICATION_SECONDS,
    clamp_notification_seconds,
)
from .users import UsersAdminWidget
from .utils import apply_glassmorphism, apply_page_layout, make_page_header


def _colon(text: str) -> str:
    """Form label text with exactly one trailing colon (locales differ)."""
    text = text.rstrip()
    return text if text.endswith((":", "：")) else f"{text}:"


def _mnemonic_safe(text: str) -> str:
    """Escape ``&`` so Qt does not treat it as a keyboard-mnemonic marker."""
    return text.replace("&", "&&")


def _hint_label() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setObjectName("SettingsHint")
    label.setProperty("hint", True)
    return label


def _scrollable(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(content)
    return area


class SettingsWidget(QWidget):
    """Settings widget"""

    theme_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)
    notification_timeout_changed = pyqtSignal(int)
    settings_saved = pyqtSignal()

    _SAVABLE_TABS = {0, 1, 2, 4}

    def __init__(self):
        super().__init__()
        self.secure_store = SecureStore()
        self.i18n = get_i18n_manager()
        self.theme_manager = get_theme_manager()
        self.settings = self.secure_store.get_settings()
        self.jobs = JobRunner(self)
        self.init_ui()
        self._update_texts()
        self.apply_rbac()

    # ------------------------------------------------------------------ UI

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        apply_page_layout(layout)
        t = self.i18n.translate
        self.page_header = make_page_header(
            t("tabs.settings"),
            t(
                "settings.page_subtitle",
                default="Theme, language, Safe Mode, and Users & RBAC",
            ),
        )
        layout.addWidget(self.page_header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "")
        self.tabs.addTab(_scrollable(self._build_backups_tab()), "")
        self.tabs.addTab(_scrollable(self._build_notifications_tab()), "")
        self.users_admin = UsersAdminWidget()
        self.tabs.addTab(_scrollable(self._wrap(self.users_admin)), "")
        self.tabs.addTab(self._build_updates_tab(), "")
        self.tabs.currentChanged.connect(self._sync_save_button)
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.save_status_label = QLabel("")
        footer.addWidget(self.save_status_label, 1)
        self.save_button = QPushButton()
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._save_settings)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        self._sync_save_button()

        self.setObjectName("glassmorphism")
        apply_glassmorphism(self)

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(8, 8, 8, 8)
        box.addWidget(widget)
        box.addStretch()
        return holder

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(6)

        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        for theme_key, theme_data in THEMES.items():
            self.theme_combo.addItem(theme_data["name"], theme_key)
        index = self.theme_combo.findData(self.theme_manager.current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow(self.theme_label, self.theme_combo)

        # Accessibility: opaque sidebar / sign-in card instead of the glass material.
        self.reduce_transparency_check = QCheckBox()
        self.reduce_transparency_check.setChecked(
            self.theme_manager.reduce_transparency
        )
        self.reduce_transparency_check.toggled.connect(
            self._on_reduce_transparency_toggled
        )
        form.addRow("", self.reduce_transparency_check)

        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for lang_code, lang_data in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(
                f"{lang_data['name']} ({lang_data['native']})", lang_code
            )
        index = self.language_combo.findData(self.i18n.current_language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(self.language_label, self.language_combo)

        self.safe_mode_label = QLabel()
        self.safe_mode_check = QCheckBox()
        self.safe_mode_check.setChecked(self.settings.get("safe_mode", True))
        form.addRow(self.safe_mode_label, self.safe_mode_check)
        self.safe_mode_hint = _hint_label()
        form.addRow("", self.safe_mode_hint)

        self.auto_connect_label = QLabel()
        self.auto_connect_check = QCheckBox()
        self.auto_connect_check.setChecked(self.settings.get("auto_connect", False))
        form.addRow(self.auto_connect_label, self.auto_connect_check)
        self.auto_connect_hint = _hint_label()
        form.addRow("", self.auto_connect_hint)

        self.telemetry_label = QLabel()
        self.telemetry_check = QCheckBox()
        self.telemetry_check.setChecked(self.settings.get("telemetry", False))
        form.addRow(self.telemetry_label, self.telemetry_check)
        self.telemetry_hint = _hint_label()
        form.addRow("", self.telemetry_hint)

        outer.addLayout(form)
        outer.addStretch()
        return page

    def _build_backups_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)

        self.adapters_group = QGroupBox()
        g = QVBoxLayout(self.adapters_group)
        self.adapters_hint = _hint_label()
        g.addWidget(self.adapters_hint)

        self.adapters_table = QTableWidget(0, 3)
        self.adapters_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.adapters_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.adapters_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.adapters_table.verticalHeader().setVisible(False)
        self.adapters_table.setMinimumHeight(170)
        g.addWidget(self.adapters_table)

        buttons = QHBoxLayout()
        self.proton_configure_button = QPushButton()
        self.proton_configure_button.clicked.connect(self._configure_proton_drive)
        buttons.addWidget(self.proton_configure_button)
        self.s3_configure_button = QPushButton()
        self.s3_configure_button.clicked.connect(self._configure_s3)
        buttons.addWidget(self.s3_configure_button)
        buttons.addStretch()
        g.addLayout(buttons)
        # Kept for callers that read the Proton status text directly.
        self.proton_status_label = QLabel("")
        self.proton_status_label.setWordWrap(True)
        self.proton_status_label.setVisible(False)
        outer.addWidget(self.adapters_group)

        self.experimental_group = QGroupBox()
        e = QVBoxLayout(self.experimental_group)
        self.experimental_restore_check = QCheckBox()
        experimental = dict(self.settings.get("experimental") or {})
        self.experimental_restore_check.setChecked(
            bool(experimental.get("restore", True))
        )
        e.addWidget(self.experimental_restore_check)
        self.experimental_hint = _hint_label()
        e.addWidget(self.experimental_hint)
        outer.addWidget(self.experimental_group)

        self._init_retention_state()
        self.retention_group = QGroupBox()
        retention = QVBoxLayout(self.retention_group)
        retention_form = QFormLayout()
        self.retention_connection_label = QLabel()
        self.retention_connection = QComboBox()
        self.retention_connection.currentIndexChanged.connect(
            self._on_retention_target_changed
        )
        retention_form.addRow(
            self.retention_connection_label, self.retention_connection
        )
        self.retention_custom = QCheckBox()
        self.retention_custom.toggled.connect(self._on_retention_custom_toggled)
        retention_form.addRow("", self.retention_custom)
        self.retention_enable = QCheckBox()
        retention_form.addRow("", self.retention_enable)
        self.retention_daily_label = QLabel()
        self.retention_daily = QSpinBox()
        self.retention_daily.setRange(0, 3660)
        retention_form.addRow(self.retention_daily_label, self.retention_daily)
        self.retention_monthly_label = QLabel()
        self.retention_monthly = QSpinBox()
        self.retention_monthly.setRange(0, 240)
        retention_form.addRow(self.retention_monthly_label, self.retention_monthly)
        retention.addLayout(retention_form)
        self.retention_hint = _hint_label()
        retention.addWidget(self.retention_hint)
        outer.addWidget(self.retention_group)
        self._reload_retention_connections()

        outer.addStretch()
        return page

    def _build_notifications_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)

        self.alerts_group = QGroupBox()
        form = QFormLayout(self.alerts_group)
        form.setHorizontalSpacing(16)

        self.notifications_label = QLabel()
        self.notifications_check = QCheckBox()
        self.notifications_check.setChecked(self.settings.get("notifications", True))
        form.addRow(self.notifications_label, self.notifications_check)

        self.notification_timeout_label = QLabel()
        self.notification_timeout_spin = QSpinBox()
        self.notification_timeout_spin.setRange(
            MIN_NOTIFICATION_SECONDS, MAX_NOTIFICATION_SECONDS
        )
        self.notification_timeout_spin.setValue(
            clamp_notification_seconds(
                self.settings.get(
                    "notification_timeout_seconds", DEFAULT_NOTIFICATION_SECONDS
                )
            )
        )
        form.addRow(
            self.notification_timeout_label, self.notification_timeout_spin
        )

        self.autostart_label = QLabel()
        self.autostart_combo = QComboBox()
        form.addRow(self.autostart_label, self.autostart_combo)
        self.autostart_hint = _hint_label()
        form.addRow("", self.autostart_hint)
        outer.addWidget(self.alerts_group)

        self.email_group = QGroupBox()
        email_form = QFormLayout(self.email_group)
        email_form.setHorizontalSpacing(16)
        email = resolve_email_config(self.settings)
        self._email_password_stored = bool(email.get("password"))

        self.email_hint = _hint_label()
        email_form.addRow(self.email_hint)

        self.email_host_label = QLabel()
        self.email_host_edit = QLineEdit(str(email.get("host") or ""))
        self.email_host_edit.setPlaceholderText("smtp.example.com")
        email_form.addRow(self.email_host_label, self.email_host_edit)

        self.email_port_label = QLabel()
        self.email_port_spin = QSpinBox()
        self.email_port_spin.setRange(1, 65535)
        self.email_port_spin.setValue(int(email.get("port") or 587))
        email_form.addRow(self.email_port_label, self.email_port_spin)

        self.email_security_label = QLabel()
        self.email_security_combo = QComboBox()
        for mode in EMAIL_SECURITY_MODES:
            self.email_security_combo.addItem(mode.upper(), mode)
        idx = self.email_security_combo.findData(email.get("security"))
        self.email_security_combo.setCurrentIndex(max(idx, 0))
        email_form.addRow(self.email_security_label, self.email_security_combo)

        self.email_user_label = QLabel()
        self.email_user_edit = QLineEdit(str(email.get("username") or ""))
        email_form.addRow(self.email_user_label, self.email_user_edit)

        self.email_password_label = QLabel()
        self.email_password_edit = QLineEdit()
        self.email_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        email_form.addRow(self.email_password_label, self.email_password_edit)

        self.email_sender_label = QLabel()
        self.email_sender_edit = QLineEdit(str(email.get("sender") or ""))
        self.email_sender_edit.setPlaceholderText("alerts@example.com")
        email_form.addRow(self.email_sender_label, self.email_sender_edit)

        self.email_recipients_label = QLabel()
        self.email_recipients_edit = QLineEdit(
            ", ".join(email.get("recipients") or [])
        )
        self.email_recipients_edit.setPlaceholderText(
            "oncall@example.com, dba@example.com"
        )
        email_form.addRow(self.email_recipients_label, self.email_recipients_edit)

        self.email_severity_label = QLabel()
        self.email_severity_combo = QComboBox()
        self.email_severity_combo.addItem("", "critical")
        self.email_severity_combo.addItem("", "warning")
        idx = self.email_severity_combo.findData(email.get("min_severity"))
        self.email_severity_combo.setCurrentIndex(max(idx, 0))
        email_form.addRow(self.email_severity_label, self.email_severity_combo)

        self.email_cooldown_label = QLabel()
        self.email_cooldown_spin = QSpinBox()
        self.email_cooldown_spin.setRange(1, 24 * 60)
        self.email_cooldown_spin.setValue(int(email.get("cooldown_minutes") or 30))
        email_form.addRow(self.email_cooldown_label, self.email_cooldown_spin)

        test_row = QHBoxLayout()
        self.email_test_button = QPushButton()
        self.email_test_button.clicked.connect(self._send_test_email)
        test_row.addWidget(self.email_test_button)
        self.email_status_label = QLabel("")
        self.email_status_label.setWordWrap(True)
        test_row.addWidget(self.email_status_label, 1)
        email_form.addRow(test_row)
        outer.addWidget(self.email_group)

        webhook = resolve_webhook_config(self.settings)
        slack = resolve_slack_config(self.settings)
        self.webhook_group = QGroupBox()
        webhook_form = QFormLayout(self.webhook_group)
        self.webhook_hint = _hint_label()
        webhook_form.addRow(self.webhook_hint)
        self.webhook_url_label = QLabel()
        self.webhook_url_edit = QLineEdit(str(webhook.get("url") or ""))
        self.webhook_url_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook_url_edit.setPlaceholderText("https://example.com/hooks/dsm")
        webhook_form.addRow(self.webhook_url_label, self.webhook_url_edit)
        self.webhook_severity_label = QLabel()
        self.webhook_severity_combo = QComboBox()
        self.webhook_severity_combo.addItem("", "critical")
        self.webhook_severity_combo.addItem("", "warning")
        idx = self.webhook_severity_combo.findData(webhook.get("min_severity"))
        self.webhook_severity_combo.setCurrentIndex(max(idx, 0))
        webhook_form.addRow(self.webhook_severity_label, self.webhook_severity_combo)
        self.webhook_cooldown_label = QLabel()
        self.webhook_cooldown_spin = QSpinBox()
        self.webhook_cooldown_spin.setRange(1, 24 * 60)
        self.webhook_cooldown_spin.setValue(int(webhook.get("cooldown_minutes") or 30))
        webhook_form.addRow(self.webhook_cooldown_label, self.webhook_cooldown_spin)
        outer.addWidget(self.webhook_group)

        self.slack_group = QGroupBox()
        slack_form = QFormLayout(self.slack_group)
        self.slack_hint = _hint_label()
        slack_form.addRow(self.slack_hint)
        self.slack_url_label = QLabel()
        self.slack_url_edit = QLineEdit(str(slack.get("url") or ""))
        self.slack_url_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.slack_url_edit.setPlaceholderText("https://hooks.slack.com/services/…")
        slack_form.addRow(self.slack_url_label, self.slack_url_edit)
        self.slack_severity_label = QLabel()
        self.slack_severity_combo = QComboBox()
        self.slack_severity_combo.addItem("", "critical")
        self.slack_severity_combo.addItem("", "warning")
        idx = self.slack_severity_combo.findData(slack.get("min_severity"))
        self.slack_severity_combo.setCurrentIndex(max(idx, 0))
        slack_form.addRow(self.slack_severity_label, self.slack_severity_combo)
        self.slack_cooldown_label = QLabel()
        self.slack_cooldown_spin = QSpinBox()
        self.slack_cooldown_spin.setRange(1, 24 * 60)
        self.slack_cooldown_spin.setValue(int(slack.get("cooldown_minutes") or 30))
        slack_form.addRow(self.slack_cooldown_label, self.slack_cooldown_spin)
        outer.addWidget(self.slack_group)

        discord = resolve_discord_config(self.settings)
        self.discord_group = QGroupBox()
        discord_form = QFormLayout(self.discord_group)
        self.discord_hint = _hint_label()
        discord_form.addRow(self.discord_hint)
        self.discord_url_label = QLabel()
        self.discord_url_edit = QLineEdit(str(discord.get("url") or ""))
        self.discord_url_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_url_edit.setPlaceholderText("https://discord.com/api/webhooks/…")
        discord_form.addRow(self.discord_url_label, self.discord_url_edit)
        self.discord_severity_label = QLabel()
        self.discord_severity_combo = QComboBox()
        self.discord_severity_combo.addItem("", "critical")
        self.discord_severity_combo.addItem("", "warning")
        idx = self.discord_severity_combo.findData(discord.get("min_severity"))
        self.discord_severity_combo.setCurrentIndex(max(idx, 0))
        discord_form.addRow(self.discord_severity_label, self.discord_severity_combo)
        self.discord_cooldown_label = QLabel()
        self.discord_cooldown_spin = QSpinBox()
        self.discord_cooldown_spin.setRange(1, 24 * 60)
        self.discord_cooldown_spin.setValue(int(discord.get("cooldown_minutes") or 30))
        discord_form.addRow(self.discord_cooldown_label, self.discord_cooldown_spin)
        outer.addWidget(self.discord_group)

        telegram = resolve_telegram_config(self.settings)
        self.telegram_group = QGroupBox()
        telegram_form = QFormLayout(self.telegram_group)
        self.telegram_hint = _hint_label()
        telegram_form.addRow(self.telegram_hint)
        self.telegram_token_label = QLabel()
        self.telegram_token_edit = QLineEdit(str(telegram.get("bot_token") or ""))
        self.telegram_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        telegram_form.addRow(self.telegram_token_label, self.telegram_token_edit)
        self.telegram_chat_label = QLabel()
        self.telegram_chat_edit = QLineEdit(str(telegram.get("chat_id") or ""))
        telegram_form.addRow(self.telegram_chat_label, self.telegram_chat_edit)
        self.telegram_severity_label = QLabel()
        self.telegram_severity_combo = QComboBox()
        self.telegram_severity_combo.addItem("", "critical")
        self.telegram_severity_combo.addItem("", "warning")
        idx = self.telegram_severity_combo.findData(telegram.get("min_severity"))
        self.telegram_severity_combo.setCurrentIndex(max(idx, 0))
        telegram_form.addRow(self.telegram_severity_label, self.telegram_severity_combo)
        self.telegram_cooldown_label = QLabel()
        self.telegram_cooldown_spin = QSpinBox()
        self.telegram_cooldown_spin.setRange(1, 24 * 60)
        self.telegram_cooldown_spin.setValue(int(telegram.get("cooldown_minutes") or 30))
        telegram_form.addRow(self.telegram_cooldown_label, self.telegram_cooldown_spin)
        outer.addWidget(self.telegram_group)

        outer.addStretch()
        return page

    def _build_updates_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.updates_panel = UpdatesPanel()
        outer.addWidget(self.updates_panel)
        return page

    def open_updates_tab(self, *, check: bool = False) -> None:
        """Show the Updates tab. ``check`` compares with GitHub Releases."""
        self.tabs.setCurrentIndex(4)
        if check:
            self.updates_panel.check_updates(notify=False)

    def _sync_save_button(self, index: int = -1) -> None:
        """Save sits bottom-right only on tabs that persist preferences."""
        if index < 0:
            index = self.tabs.currentIndex()
        show = index in self._SAVABLE_TABS
        self.save_button.setVisible(show)
        self.save_status_label.setVisible(show)

    # ------------------------------------------------------------- state

    def apply_rbac(self) -> None:
        """Enable/disable settings editing based on current permissions."""
        auth = get_auth_manager()
        can_write = auth.has_permission("settings:write")
        editable = can_write or not auth.is_rbac_active()
        self.save_button.setEnabled(can_write)
        for widget in (
            self.safe_mode_check,
            self.auto_connect_check,
            self.notifications_check,
            self.notification_timeout_spin,
            self.telemetry_check,
            self.proton_configure_button,
            self.s3_configure_button,
            self.autostart_combo,
            self.email_host_edit,
            self.email_port_spin,
            self.email_security_combo,
            self.email_user_edit,
            self.email_password_edit,
            self.email_sender_edit,
            self.email_recipients_edit,
            self.email_severity_combo,
            self.email_cooldown_spin,
            self.email_test_button,
            self.webhook_url_edit,
            self.webhook_severity_combo,
            self.webhook_cooldown_spin,
            self.slack_url_edit,
            self.slack_severity_combo,
            self.slack_cooldown_spin,
            self.discord_url_edit,
            self.discord_severity_combo,
            self.discord_cooldown_spin,
            self.telegram_token_edit,
            self.telegram_chat_edit,
            self.telegram_severity_combo,
            self.telegram_cooldown_spin,
        ):
            widget.setEnabled(editable)
        self.updates_panel.set_editable(editable)
        self._apply_retention_field_enabled()
        # Experimental toggle: editable only with settings:write, and never
        # when the environment already forces it on.
        forced = env_forces_experimental()
        self.experimental_restore_check.setEnabled(editable and not forced)
        if forced:
            self.experimental_restore_check.setChecked(True)
        # Theme/language preview still allowed for viewers when RBAC on
        self.theme_combo.setEnabled(True)
        self.language_combo.setEnabled(True)
        self.users_admin.refresh()
        self._refresh_adapters()

    def refresh_connection_choices(self) -> None:
        """Rebuild the auto-start monitoring choices from saved connections."""
        t = self.i18n.translate
        selected = (self.settings.get("monitoring") or {}).get(
            "autostart_connection_id"
        )
        if self.autostart_combo.count():
            selected = self.autostart_combo.currentData() or selected
        self.autostart_combo.blockSignals(True)
        self.autostart_combo.clear()
        self.autostart_combo.addItem(
            t("settings.autostart_none", default="Do not start automatically"), None
        )
        try:
            connections = self.secure_store.get_connections()
        except Exception:
            connections = []
        for conn in connections:
            self.autostart_combo.addItem(
                str(conn.get("name") or conn.get("id")), conn.get("id")
            )
        idx = self.autostart_combo.findData(selected)
        self.autostart_combo.setCurrentIndex(max(idx, 0))
        self.autostart_combo.blockSignals(False)
        self._reload_retention_connections()

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        self.refresh_connection_choices()
        self._refresh_adapters()

    # ----------------------------------------------------------- adapters

    def _adapter_rows(self) -> List[Dict[str, str]]:
        t = self.i18n.translate
        ready = t("settings.adapter_ready", default="Ready")
        missing = t("settings.adapter_not_configured", default="Not configured")
        rows: List[Dict[str, str]] = [
            {
                "name": t("backups.local", default="Local"),
                "status": ready,
                "detail": t(
                    "settings.adapter_local_detail",
                    default="Files in the app data folder with a SHA-256 sidecar",
                ),
            }
        ]
        proton = proton_drive_status()
        if proton.get("configured"):
            proton_detail = f"{proton.get('remote')}:{proton.get('remote_path')}"
        else:
            proton_detail = str(proton.get("error") or proton.get("message") or "")
        rows.append(
            {
                "name": "Proton Drive",
                "status": ready if proton.get("configured") else missing,
                "detail": proton_detail,
            }
        )
        s3 = s3_status()
        if s3.get("configured"):
            s3_detail = f"{s3.get('bucket')} · {s3.get('credentials')}"
        else:
            s3_detail = str(s3.get("error") or "")
        rows.append(
            {
                "name": t("settings.adapter_s3", default="S3-compatible"),
                "status": ready if s3.get("configured") else missing,
                "detail": s3_detail,
            }
        )
        have_gdrive = all(
            importlib.util.find_spec(mod) is not None
            for mod in ("googleapiclient", "google.oauth2")
        )
        rows.append(
            {
                "name": "Google Drive",
                "status": t("settings.adapter_api_only", default="API only"),
                "detail": t(
                    "settings.adapter_gdrive_detail",
                    default=(
                        "Library adapter for scripts and plugins; not offered "
                        "in the UI (OAuth tokens are too sensitive for a "
                        "desktop form). Google client libraries installed: {state}"
                    ),
                    state=t("common.yes") if have_gdrive else t("common.no"),
                ),
            }
        )
        return rows

    def _refresh_adapters(self) -> None:
        rows = self._adapter_rows()
        self.adapters_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("name", "status", "detail")):
                item = QTableWidgetItem(row[key])
                item.setToolTip(row[key])
                self.adapters_table.setItem(r, c, item)
        # Keep the legacy status label in sync for callers reading it.
        self._refresh_proton_status()

    def _refresh_proton_status(self) -> None:
        status = proton_drive_status()
        t = self.i18n.translate
        if status.get("configured"):
            self.proton_status_label.setText(
                t(
                    "backups.proton_ready",
                    remote=status.get("remote"),
                    path=status.get("remote_path"),
                )
            )
        else:
            self.proton_status_label.setText(
                t(
                    "backups.proton_not_configured",
                    error=status.get("error") or status.get("message") or "",
                )
            )

    def _configure_proton_drive(self) -> None:
        if open_proton_drive_config(self):
            self._refresh_adapters()
            self.settings_saved.emit()

    def _configure_s3(self) -> None:
        if open_s3_config(self):
            self._refresh_adapters()
            self.settings_saved.emit()

    # -------------------------------------------------------------- email

    def _email_form_config(self) -> Dict[str, Any]:
        """Current form values as an email config (password: field or stored)."""
        stored = resolve_email_config(self.secure_store.get_settings())
        recipients = [
            r.strip()
            for r in self.email_recipients_edit.text().replace(";", ",").split(",")
            if r.strip()
        ]
        password = self.email_password_edit.text()
        return {
            "host": self.email_host_edit.text().strip(),
            "port": int(self.email_port_spin.value()),
            "security": str(self.email_security_combo.currentData()),
            "username": self.email_user_edit.text().strip(),
            "password": password if password else stored.get("password") or "",
            "sender": self.email_sender_edit.text().strip(),
            "recipients": recipients,
            "min_severity": str(self.email_severity_combo.currentData()),
            "cooldown_minutes": int(self.email_cooldown_spin.value()),
        }

    def _send_test_email(self) -> None:
        t = self.i18n.translate
        cfg = self._email_form_config()
        problems = validate_email_config(cfg)
        if problems:
            self.email_status_label.setText("; ".join(problems))
            return
        self.email_test_button.setEnabled(False)
        self.email_status_label.setText(
            t("settings.email_test_sending", default="Sending test email…")
        )

        def _done(_result) -> None:
            self.email_test_button.setEnabled(True)
            self.email_status_label.setText(
                t(
                    "settings.email_test_ok",
                    default="Test email sent to {recipients}.",
                    recipients=", ".join(cfg["recipients"]),
                )
            )

        def _failed(message: str) -> None:
            self.email_test_button.setEnabled(True)
            self.email_status_label.setText(
                t(
                    "settings.email_test_failed",
                    default="Test email failed: {error}",
                    error=message,
                )
            )

        if not self.jobs.submit(
            "settings-email-test", lambda: send_test_email(cfg), _done, _failed
        ):
            self.email_test_button.setEnabled(True)

    # ------------------------------------------------------------- texts

    def _update_texts(self):
        """Update all text labels with translations"""
        t = self.i18n.translate
        titles = (
            t("settings.tab_general", default="General"),
            t("settings.tab_backups", default="Backups & Adapters"),
            t("settings.tab_notifications", default="Notifications"),
            t("auth.users_group", default="Users & RBAC"),
            t("settings.tab_updates", default="Updates"),
        )
        for i, title in enumerate(titles):
            self.tabs.setTabText(i, _mnemonic_safe(title))

        self.theme_label.setText(_colon(t("settings.theme")))
        self.reduce_transparency_check.setText(
            t(
                "settings.reduce_transparency",
                default="Reduce transparency (opaque sidebar and sign-in card)",
            )
        )
        self.language_label.setText(_colon(t("settings.language")))
        self.safe_mode_label.setText(_colon(t("settings.safe_mode")))
        self.auto_connect_label.setText(_colon(t("settings.auto_connect")))
        self.telemetry_label.setText(_colon(t("settings.telemetry")))
        self.safe_mode_hint.setText(
            t(
                "settings.safe_mode_hint",
                default="Blocks destructive SQL (DROP, TRUNCATE, DELETE without WHERE) until you confirm.",
            )
        )
        self.auto_connect_hint.setText(
            t(
                "settings.auto_connect_hint",
                default="Reconnects the last used connection when the app starts.",
            )
        )
        self.telemetry_hint.setText(
            t(
                "settings.telemetry_hint",
                default="Off by default. Nothing leaves this machine unless you turn it on.",
            )
        )

        self.adapters_group.setTitle(
            _mnemonic_safe(
                t("settings.adapters_title", default="Backup destinations")
            )
        )
        self.adapters_hint.setText(
            t(
                "settings.adapters_hint",
                default=(
                    "Local backups stay on this machine. Off-machine "
                    "destinations (Proton Drive, S3) always upload encrypted "
                    "archives."
                ),
            )
        )
        self.adapters_table.setHorizontalHeaderLabels(
            [
                t("backups.schedule_col_adapter", default="Adapter"),
                t("backups.col_status"),
                t("settings.adapter_details", default="Details"),
            ]
        )
        self.proton_configure_button.setText(
            t("backups.configure_proton", default="Configure Proton Drive…")
        )
        self.s3_configure_button.setText(
            t("settings.configure_s3", default="Configure S3…")
        )
        self.experimental_group.setTitle(
            t("settings.experimental_title", default="Full restore")
        )
        self.experimental_restore_check.setText(
            t(
                "settings.experimental_restore",
                default="Show Restore Backup on the Backups tab",
            )
        )
        hint = t(
            "settings.experimental_restore_hint",
            default=(
                "Full restore is stable and on by default. Uncheck to hide "
                "the Restore button. A restore still overwrites the target "
                "database, so it needs the backups:restore permission, a "
                "typed confirmation, and a safety backup."
            ),
        )
        if env_forces_experimental():
            hint += "\n" + t(
                "settings.experimental_env_forced",
                default="Forced on by the {var} environment variable.",
                var=EXPERIMENTAL_ENV_VAR,
            )
        self.experimental_hint.setText(hint)

        self.alerts_group.setTitle(
            _mnemonic_safe(t("settings.alerts_title", default="Alerts & monitoring"))
        )
        self.notifications_label.setText(_colon(t("settings.notifications")))
        self.notification_timeout_label.setText(
            _colon(t("settings.notification_timeout"))
        )
        self.notification_timeout_spin.setSuffix(
            f" {t('settings.seconds_suffix')}"
        )
        self.autostart_label.setText(
            _colon(
                t(
                    "settings.autostart_monitoring",
                    default="Start monitoring on launch",
                )
            )
        )
        self.autostart_hint.setText(
            t(
                "settings.autostart_hint",
                default=(
                    "Watch this connection as soon as the app opens, so a "
                    "monitoring user gets real-time alerts without clicking "
                    "Start."
                ),
            )
        )
        self.refresh_connection_choices()

        self.email_group.setTitle(
            t("settings.email_title", default="Email alerts (SMTP)")
        )
        self.email_hint.setText(
            t(
                "settings.email_hint",
                default=(
                    "Sends critical alerts through your own SMTP server. The "
                    "password is stored encrypted in SecureStore. Enable the "
                    "Email channel on the Monitoring tab. Plain SMTP is only "
                    "allowed for localhost."
                ),
            )
        )
        self.email_host_label.setText(
            _colon(t("settings.email_host", default="SMTP host"))
        )
        self.email_port_label.setText(
            _colon(t("settings.email_port", default="Port"))
        )
        self.email_security_label.setText(
            _colon(t("settings.email_security", default="Security"))
        )
        self.email_user_label.setText(
            _colon(t("settings.email_username", default="Username"))
        )
        self.email_password_label.setText(
            _colon(t("settings.email_password", default="Password"))
        )
        self.email_password_edit.setPlaceholderText(
            t(
                "settings.email_password_set",
                default="Stored — leave blank to keep",
            )
            if self._email_password_stored
            else ""
        )
        self.email_sender_label.setText(
            _colon(t("settings.email_sender", default="From address"))
        )
        self.email_recipients_label.setText(
            _colon(
                t(
                    "settings.email_recipients",
                    default="Recipients (comma-separated)",
                )
            )
        )
        self.email_severity_label.setText(
            _colon(t("settings.email_min_severity", default="Minimum severity"))
        )
        self.email_severity_combo.setItemText(
            0, t("settings.severity_critical", default="Critical only")
        )
        self.email_severity_combo.setItemText(
            1, t("settings.severity_warning", default="Warning and critical")
        )
        self.email_cooldown_label.setText(
            _colon(t("settings.email_cooldown", default="Repeat cooldown"))
        )
        self.email_cooldown_spin.setSuffix(
            f" {t('settings.minutes_suffix', default='min')}"
        )
        self.email_test_button.setText(
            t("settings.email_test", default="Send test email")
        )

        self.webhook_group.setTitle(
            t("settings.webhook_title", default="Webhook alerts")
        )
        self.webhook_hint.setText(
            t(
                "settings.webhook_hint",
                default=(
                    "POSTs a JSON alert to an https URL you control. The URL is "
                    "stored encrypted and is not written to the notification log. "
                    "http is only allowed for localhost. Enable Webhook on the "
                    "Monitoring tab. Same severity and cooldown rules as email."
                ),
            )
        )
        self.webhook_url_label.setText(
            _colon(t("settings.webhook_url", default="Webhook URL"))
        )
        self.webhook_severity_label.setText(
            _colon(t("settings.email_min_severity", default="Minimum severity"))
        )
        self.webhook_severity_combo.setItemText(
            0, t("settings.severity_critical", default="Critical only")
        )
        self.webhook_severity_combo.setItemText(
            1, t("settings.severity_warning", default="Warning and critical")
        )
        self.webhook_cooldown_label.setText(
            _colon(t("settings.email_cooldown", default="Repeat cooldown"))
        )
        self.webhook_cooldown_spin.setSuffix(
            f" {t('settings.minutes_suffix', default='min')}"
        )
        self.slack_group.setTitle(
            t("settings.slack_title", default="Slack alerts")
        )
        self.slack_hint.setText(
            t(
                "settings.slack_hint",
                default=(
                    "Posts to a Slack incoming webhook (https://hooks.slack.com). "
                    "The URL contains a secret and stays in SecureStore. Same "
                    "severity and cooldown rules as email."
                ),
            )
        )
        self.slack_url_label.setText(
            _colon(t("settings.slack_url", default="Slack webhook URL"))
        )
        self.slack_severity_label.setText(
            _colon(t("settings.email_min_severity", default="Minimum severity"))
        )
        self.slack_severity_combo.setItemText(
            0, t("settings.severity_critical", default="Critical only")
        )
        self.slack_severity_combo.setItemText(
            1, t("settings.severity_warning", default="Warning and critical")
        )
        self.slack_cooldown_label.setText(
            _colon(t("settings.email_cooldown", default="Repeat cooldown"))
        )
        self.slack_cooldown_spin.setSuffix(
            f" {t('settings.minutes_suffix', default='min')}"
        )
        self.discord_group.setTitle(
            t("settings.discord_title", default="Discord alerts")
        )
        self.discord_hint.setText(
            t(
                "settings.discord_hint",
                default=(
                    "Posts to a Discord incoming webhook "
                    "(https://discord.com/api/webhooks/…). The URL contains a "
                    "secret and stays in SecureStore. Off until you enable "
                    "Discord on the Monitoring tab. Same severity and cooldown "
                    "rules as email."
                ),
            )
        )
        self.discord_url_label.setText(
            _colon(t("settings.discord_url", default="Discord webhook URL"))
        )
        self.discord_severity_label.setText(
            _colon(t("settings.email_min_severity", default="Minimum severity"))
        )
        self.discord_severity_combo.setItemText(
            0, t("settings.severity_critical", default="Critical only")
        )
        self.discord_severity_combo.setItemText(
            1, t("settings.severity_warning", default="Warning and critical")
        )
        self.discord_cooldown_label.setText(
            _colon(t("settings.email_cooldown", default="Repeat cooldown"))
        )
        self.discord_cooldown_spin.setSuffix(
            f" {t('settings.minutes_suffix', default='min')}"
        )
        self.telegram_group.setTitle(
            t("settings.telegram_title", default="Telegram alerts")
        )
        self.telegram_hint.setText(
            t(
                "settings.telegram_hint",
                default=(
                    "Posts through the official Bot API (api.telegram.org only). "
                    "The bot token and chat id stay in SecureStore and are not "
                    "written to the notification log. Off until you enable "
                    "Telegram on the Monitoring tab."
                ),
            )
        )
        self.telegram_token_label.setText(
            _colon(t("settings.telegram_token", default="Bot token"))
        )
        self.telegram_chat_label.setText(
            _colon(t("settings.telegram_chat_id", default="Chat id"))
        )
        self.telegram_severity_label.setText(
            _colon(t("settings.email_min_severity", default="Minimum severity"))
        )
        self.telegram_severity_combo.setItemText(
            0, t("settings.severity_critical", default="Critical only")
        )
        self.telegram_severity_combo.setItemText(
            1, t("settings.severity_warning", default="Warning and critical")
        )
        self.telegram_cooldown_label.setText(
            _colon(t("settings.email_cooldown", default="Repeat cooldown"))
        )
        self.telegram_cooldown_spin.setSuffix(
            f" {t('settings.minutes_suffix', default='min')}"
        )

        self.updates_panel.retranslate()
        self.retention_group.setTitle(
            _mnemonic_safe(t("settings.retention_title", default="Retention"))
        )
        self.retention_connection_label.setText(
            _colon(t("settings.retention_connection", default="Connection"))
        )
        if self.retention_connection.count():
            self.retention_connection.setItemText(
                0, t("settings.retention_all", default="All connections (default)")
            )
        self.retention_custom.setText(
            t(
                "settings.retention_custom",
                default="Custom rules for the selected connection",
            )
        )
        self.retention_enable.setText(
            t(
                "settings.retention_enable",
                default="Prune old backups for this rule",
            )
        )
        self.retention_daily_label.setText(
            _colon(t("settings.retention_daily", default="Keep daily"))
        )
        self.retention_monthly_label.setText(
            _colon(t("settings.retention_monthly", default="Keep monthly"))
        )
        self.retention_hint.setText(
            t(
                "settings.retention_hint",
                default=(
                    "Off by default. After a scheduled backup, Local, Proton "
                    "Drive and S3 copies older than these rules are deleted. "
                    "Google Drive is not pruned. If both counts are zero, "
                    "nothing is deleted."
                ),
            )
        )
        self.save_button.setText(t("settings.save"))
        self.save_button.setIcon(themed_icon("save", filled=True))
        self.save_button.setIconSize(QSize(16, 16))
        self.users_admin.retranslate()
        self._refresh_adapters()

    # ------------------------------------------------------------ handlers

    def _on_theme_changed(self, index):
        """Handle theme change"""
        theme_key = self.theme_combo.itemData(index)
        if theme_key:
            self.theme_manager.set_theme(theme_key)
            self.theme_changed.emit(theme_key)

    def _on_reduce_transparency_toggled(self, checked: bool) -> None:
        """Persist the accessibility preference and repaint the shell."""
        self.theme_manager.set_reduce_transparency(checked)
        self.theme_changed.emit(self.theme_manager.current_theme)

    def _on_language_changed(self, index):
        """Handle language change"""
        lang_code = self.language_combo.itemData(index)
        if lang_code:
            self.i18n.set_language(lang_code)
            self._update_texts()
            self.language_changed.emit(lang_code)

    def _init_retention_state(self) -> None:
        raw = self.settings.get("retention") or {}
        connections = raw.get("connections") if isinstance(raw.get("connections"), dict) else {}
        daily = raw.get("keep_daily")
        monthly = raw.get("keep_monthly")
        self._retention_state = {
            "default": {
                "enabled": bool(raw.get("enabled", False)),
                "keep_daily": int(7 if daily is None else daily),
                "keep_monthly": int(6 if monthly is None else monthly),
            },
            "connections": {},
        }
        for key, value in connections.items():
            if not isinstance(value, dict):
                continue
            self._retention_state["connections"][str(key)] = {
                "enabled": bool(value.get("enabled", False)),
                "keep_daily": int(value.get("keep_daily") or 0),
                "keep_monthly": int(value.get("keep_monthly") or 0),
            }
        self._retention_showing = None
        self._retention_loading = False
        self._retention_form_ready = False

    def _retention_editable(self) -> bool:
        auth = get_auth_manager()
        return auth.has_permission("settings:write") or not auth.is_rbac_active()

    def _apply_retention_field_enabled(self) -> None:
        if not hasattr(self, "retention_enable"):
            return
        editable = self._retention_editable()
        on_connection = self._retention_showing is not None
        fields_on = editable and (
            not on_connection or self.retention_custom.isChecked()
        )
        self.retention_connection.setEnabled(editable)
        self.retention_custom.setEnabled(editable and on_connection)
        self.retention_enable.setEnabled(fields_on)
        self.retention_daily.setEnabled(fields_on)
        self.retention_monthly.setEnabled(fields_on)

    def _flush_retention_form(self) -> None:
        if not getattr(self, "_retention_form_ready", False):
            return
        if getattr(self, "_retention_loading", False):
            return
        data = {
            "enabled": self.retention_enable.isChecked(),
            "keep_daily": int(self.retention_daily.value()),
            "keep_monthly": int(self.retention_monthly.value()),
        }
        target = self._retention_showing
        if target is None:
            self._retention_state["default"] = data
        elif self.retention_custom.isChecked():
            self._retention_state["connections"][str(target)] = data
        else:
            self._retention_state["connections"].pop(str(target), None)

    def _load_retention_form(self, target) -> None:
        self._retention_loading = True
        try:
            self._retention_showing = target
            custom = target is not None and str(target) in self._retention_state["connections"]
            self.retention_custom.setVisible(target is not None)
            self.retention_custom.setChecked(custom)
            if target is None or not custom:
                data = self._retention_state["default"]
            else:
                data = self._retention_state["connections"][str(target)]
            self.retention_enable.setChecked(bool(data["enabled"]))
            self.retention_daily.setValue(int(data["keep_daily"]))
            self.retention_monthly.setValue(int(data["keep_monthly"]))
        finally:
            self._retention_loading = False
            self._retention_form_ready = True
        self._apply_retention_field_enabled()

    def _on_retention_target_changed(self) -> None:
        if self._retention_loading or not self._retention_form_ready:
            return
        self._flush_retention_form()
        self._load_retention_form(self.retention_connection.currentData())

    def _on_retention_custom_toggled(self, _checked: bool) -> None:
        if self._retention_loading or not self._retention_form_ready:
            return
        self._apply_retention_field_enabled()

    def _reload_retention_connections(self) -> None:
        if not hasattr(self, "retention_connection"):
            return
        self._flush_retention_form()
        t = self.i18n.translate
        selected = self.retention_connection.currentData()
        self.retention_connection.blockSignals(True)
        self.retention_connection.clear()
        self.retention_connection.addItem(
            t("settings.retention_all", default="All connections (default)"), None
        )
        try:
            connections = self.secure_store.get_connections()
        except Exception:
            connections = []
        for conn in connections:
            self.retention_connection.addItem(
                str(conn.get("name") or conn.get("id")), conn.get("id")
            )
        idx = self.retention_connection.findData(selected)
        self.retention_connection.setCurrentIndex(max(idx, 0))
        self.retention_connection.blockSignals(False)
        self._load_retention_form(self.retention_connection.currentData())

    def _retention_payload(self) -> Dict[str, Any]:
        self._flush_retention_form()
        default = self._retention_state["default"]
        return {
            "enabled": bool(default["enabled"]),
            "keep_daily": int(default["keep_daily"]),
            "keep_monthly": int(default["keep_monthly"]),
            "connections": {
                str(key): {
                    "enabled": bool(value["enabled"]),
                    "keep_daily": int(value["keep_daily"]),
                    "keep_monthly": int(value["keep_monthly"]),
                }
                for key, value in self._retention_state["connections"].items()
            },
        }

    def _save_settings(self):
        """Save settings"""
        t = self.i18n.translate
        try:
            get_auth_manager().require("settings:write")
        except PermissionDenied as exc:
            QMessageBox.warning(
                self, t("auth.denied", default="Access denied"), str(exc)
            )
            return
        existing = self.secure_store.get_settings()
        auth = get_auth_manager()
        rbac = dict(existing.get("rbac") or DEFAULT_SETTINGS.get("rbac") or {})
        rbac["enabled"] = auth.is_rbac_active()

        email = dict(existing.get("email_alerts") or {})
        form = self._email_form_config()
        email.update(
            {
                "host": form["host"],
                "port": form["port"],
                "security": form["security"],
                "username": form["username"],
                "sender": form["sender"],
                "recipients": form["recipients"],
                "min_severity": form["min_severity"],
                "cooldown_minutes": form["cooldown_minutes"],
            }
        )
        typed_password = self.email_password_edit.text()
        if typed_password:
            email["password"] = typed_password
        if not form["username"]:
            email.pop("password", None)

        webhook = dict(existing.get("webhook_alerts") or {})
        webhook.update(
            {
                "url": self.webhook_url_edit.text().strip(),
                "min_severity": self.webhook_severity_combo.currentData() or "critical",
                "cooldown_minutes": int(self.webhook_cooldown_spin.value()),
            }
        )
        slack = dict(existing.get("slack_alerts") or {})
        slack.update(
            {
                "url": self.slack_url_edit.text().strip(),
                "min_severity": self.slack_severity_combo.currentData() or "critical",
                "cooldown_minutes": int(self.slack_cooldown_spin.value()),
            }
        )
        discord = dict(existing.get("discord_alerts") or {})
        discord.update(
            {
                "url": self.discord_url_edit.text().strip(),
                "min_severity": self.discord_severity_combo.currentData() or "critical",
                "cooldown_minutes": int(self.discord_cooldown_spin.value()),
            }
        )
        telegram = dict(existing.get("telegram_alerts") or {})
        telegram.update(
            {
                "bot_token": self.telegram_token_edit.text().strip(),
                "chat_id": self.telegram_chat_edit.text().strip(),
                "min_severity": self.telegram_severity_combo.currentData()
                or "critical",
                "cooldown_minutes": int(self.telegram_cooldown_spin.value()),
            }
        )
        telegram.pop("url", None)

        experimental = dict(existing.get("experimental") or {})
        if not env_forces_experimental():
            experimental["restore"] = self.experimental_restore_check.isChecked()

        monitoring = dict(existing.get("monitoring") or {})
        monitoring["autostart_connection_id"] = self.autostart_combo.currentData()

        # Start from what is stored so keys edited on other tabs (alert
        # thresholds/channels, dashboard layout, plugins, Proton/S3/cloud/
        # companion prefs, …) are never dropped.
        self.settings = {
            **existing,
            "theme": self.theme_manager.current_theme,
            "language": self.i18n.current_language,
            "safe_mode": self.safe_mode_check.isChecked(),
            "auto_connect": self.auto_connect_check.isChecked(),
            "notifications": self.notifications_check.isChecked(),
            "notification_timeout_seconds": int(
                self.notification_timeout_spin.value()
            ),
            "update_channel": self.updates_panel.selected_channel(),
            "update_auto_check": self.updates_panel.auto_check_enabled(),
            "retention": self._retention_payload(),
            "telemetry": self.telemetry_check.isChecked(),
            "rbac": rbac,
            "experimental": experimental,
            "email_alerts": email,
            "webhook_alerts": webhook,
            "slack_alerts": slack,
            "discord_alerts": discord,
            "telegram_alerts": telegram,
            "monitoring": monitoring,
        }
        self.secure_store.set_settings(self.settings)
        self.email_password_edit.clear()
        self._email_password_stored = bool(email.get("password"))
        self._update_texts()
        self.notification_timeout_changed.emit(
            self.settings["notification_timeout_seconds"]
        )
        self.settings_saved.emit()
        self.save_status_label.setText(t("settings.settings_saved"))
        QMessageBox.information(
            self,
            t("common.success"),
            t("settings.settings_saved"),
        )

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self.jobs.wait_all()
        super().closeEvent(event)
