"""
Settings widget
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from ..backups.protondrive import configuration_status as proton_drive_status
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore
from ..config import DEFAULT_SETTINGS
from ..i18n.manager import get_i18n_manager
from ..i18n.languages import SUPPORTED_LANGUAGES
from ..themes.manager import get_theme_manager
from ..themes.themes import THEMES
from .proton_drive_config import open_proton_drive_config
from .users import UsersAdminWidget
from .utils import apply_glassmorphism, apply_page_layout, make_page_header


class SettingsWidget(QWidget):
    """Settings widget"""

    theme_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.secure_store = SecureStore()
        self.i18n = get_i18n_manager()
        self.theme_manager = get_theme_manager()
        self.settings = self.secure_store.get_settings()
        self.init_ui()
        self._update_texts()
        self.apply_rbac()

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        apply_page_layout(layout)
        t = self.i18n.translate
        layout.addWidget(
            make_page_header(
                t("tabs.settings"),
                t(
                    "settings.page_subtitle",
                    default="Theme, language, Safe Mode, and Users & RBAC",
                ),
            )
        )

        form = QFormLayout()

        # Theme
        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        for theme_key, theme_data in THEMES.items():
            self.theme_combo.addItem(theme_data["name"], theme_key)
        current_theme = self.theme_manager.current_theme
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow(self.theme_label, self.theme_combo)

        # Language
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for lang_code, lang_data in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(
                f"{lang_data['name']} ({lang_data['native']})", lang_code
            )
        current_lang = self.i18n.current_language
        index = self.language_combo.findData(current_lang)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(self.language_label, self.language_combo)

        # Safe Mode
        self.safe_mode_label = QLabel()
        self.safe_mode_check = QCheckBox()
        self.safe_mode_check.setChecked(self.settings.get("safe_mode", True))
        form.addRow(self.safe_mode_label, self.safe_mode_check)

        # Auto Connect
        self.auto_connect_label = QLabel()
        self.auto_connect_check = QCheckBox()
        self.auto_connect_check.setChecked(self.settings.get("auto_connect", False))
        form.addRow(self.auto_connect_label, self.auto_connect_check)

        # Notifications
        self.notifications_label = QLabel()
        self.notifications_check = QCheckBox()
        self.notifications_check.setChecked(self.settings.get("notifications", True))
        form.addRow(self.notifications_label, self.notifications_check)

        # Telemetry
        self.telemetry_label = QLabel()
        self.telemetry_check = QCheckBox()
        self.telemetry_check.setChecked(self.settings.get("telemetry", False))
        form.addRow(self.telemetry_label, self.telemetry_check)

        layout.addLayout(form)

        # Proton Drive credentials (SecureStore)
        self.proton_section_label = QLabel()
        self.proton_section_label.setObjectName("PageSubtitle")
        layout.addWidget(self.proton_section_label)
        self.proton_status_label = QLabel("")
        self.proton_status_label.setWordWrap(True)
        layout.addWidget(self.proton_status_label)
        self.proton_configure_button = QPushButton()
        self.proton_configure_button.clicked.connect(self._configure_proton_drive)
        layout.addWidget(self.proton_configure_button)
        self._refresh_proton_status()

        # Save button
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self._save_settings)
        layout.addWidget(self.save_button)

        self.users_admin = UsersAdminWidget()
        layout.addWidget(self.users_admin)

        layout.addStretch()

        self.setObjectName("glassmorphism")
        apply_glassmorphism(self)

    def apply_rbac(self) -> None:
        """Enable/disable settings save based on current permissions."""
        auth = get_auth_manager()
        can_write = auth.has_permission("settings:write")
        self.save_button.setEnabled(can_write)
        for widget in (
            self.theme_combo,
            self.language_combo,
            self.safe_mode_check,
            self.auto_connect_check,
            self.notifications_check,
            self.telemetry_check,
            self.proton_configure_button,
        ):
            widget.setEnabled(can_write or not auth.is_rbac_active())
        # Theme/language preview still allowed for viewers when RBAC on
        if auth.is_rbac_active() and not can_write:
            self.theme_combo.setEnabled(True)
            self.language_combo.setEnabled(True)
        self.users_admin.refresh()

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
            self._refresh_proton_status()

    def _update_texts(self):
        """Update all text labels with translations"""
        t = self.i18n.translate
        self.theme_label.setText(f"{t('settings.theme')}:")
        self.language_label.setText(f"{t('settings.language')}:")
        self.safe_mode_label.setText(f"{t('settings.safe_mode')}:")
        self.auto_connect_label.setText(f"{t('settings.auto_connect')}:")
        self.notifications_label.setText(f"{t('settings.notifications')}:")
        self.telemetry_label.setText(f"{t('settings.telemetry')}:")
        self.proton_section_label.setText(
            t("settings.proton_drive", default="Proton Drive backups")
        )
        self.proton_configure_button.setText(
            t("backups.configure_proton", default="Configure Proton Drive…")
        )
        self.save_button.setText(t("settings.save"))
        self._refresh_proton_status()

    def _on_theme_changed(self, index):
        """Handle theme change"""
        theme_key = self.theme_combo.itemData(index)
        if theme_key:
            self.theme_manager.set_theme(theme_key)
            self.theme_changed.emit(theme_key)

    def _on_language_changed(self, index):
        """Handle language change"""
        lang_code = self.language_combo.itemData(index)
        if lang_code:
            self.i18n.set_language(lang_code)
            self._update_texts()
            self.language_changed.emit(lang_code)

    def _save_settings(self):
        """Save settings"""
        try:
            get_auth_manager().require("settings:write")
        except PermissionDenied as exc:
            QMessageBox.warning(
                self,
                self.i18n.translate("auth.denied", default="Access denied"),
                str(exc),
            )
            return
        existing = self.secure_store.get_settings()
        auth = get_auth_manager()
        rbac = dict(existing.get("rbac") or DEFAULT_SETTINGS.get("rbac") or {})
        rbac["enabled"] = auth.is_rbac_active()
        self.settings = {
            "theme": self.theme_manager.current_theme,
            "language": self.i18n.current_language,
            "safe_mode": self.safe_mode_check.isChecked(),
            "auto_connect": self.auto_connect_check.isChecked(),
            "notifications": self.notifications_check.isChecked(),
            "telemetry": self.telemetry_check.isChecked(),
            # Preserve monitoring / dashboard prefs edited in their tabs
            "alert_thresholds": existing.get(
                "alert_thresholds", DEFAULT_SETTINGS.get("alert_thresholds")
            ),
            "alert_channels": existing.get(
                "alert_channels", DEFAULT_SETTINGS.get("alert_channels")
            ),
            "dashboard_layout": existing.get(
                "dashboard_layout", DEFAULT_SETTINGS.get("dashboard_layout")
            ),
            "plugins": existing.get(
                "plugins", DEFAULT_SETTINGS.get("plugins")
            ),
            "rbac": rbac,
            # Preserve encrypted cloud / Proton / companion prefs edited elsewhere
            "proton_drive": existing.get(
                "proton_drive", DEFAULT_SETTINGS.get("proton_drive")
            ),
            "cloud_managed": existing.get(
                "cloud_managed", DEFAULT_SETTINGS.get("cloud_managed")
            ),
            "companion": existing.get(
                "companion", DEFAULT_SETTINGS.get("companion")
            ),
        }
        self.secure_store.set_settings(self.settings)
        QMessageBox.information(
            self,
            self.i18n.translate("common.success"),
            self.i18n.translate("settings.settings_saved"),
        )
