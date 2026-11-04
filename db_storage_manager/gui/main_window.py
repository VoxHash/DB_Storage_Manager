"""
Main application window — modern desktop shell with library-style navigation.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLayout,
    QMainWindow,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction

from .dashboard import DashboardWidget
from .connections import ConnectionsWidget
from .query import QueryWidget
from .backups import BackupsWidget
from .settings import SettingsWidget
from .monitoring import MonitoringWidget
from .plugins import PluginsWidget
from .sidebar import NavSidebar
from ..security.auth import get_auth_manager
from ..security.store import SecureStore
from ..i18n.manager import get_i18n_manager
from ..themes.manager import get_theme_manager
from .tray import AppTray, clamp_notification_seconds
from .icons import refresh_icons
from .utils import apply_glassmorphism, apply_theme_to_app
from ..resources import apply_app_icon

# Small floor so chrome (220px sidebar + page margins) stays usable; no max lock.
_MAIN_WINDOW_MIN_WIDTH = 800
_MAIN_WINDOW_MIN_HEIGHT = 500
_MAIN_WINDOW_DEFAULT_WIDTH = 1200
_MAIN_WINDOW_DEFAULT_HEIGHT = 800


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.secure_store = SecureStore()
        self.i18n = get_i18n_manager()
        self.theme_manager = get_theme_manager()
        self.connections = self.secure_store.get_connections()
        self._syncing_nav = False

        self.setWindowTitle(self.i18n.translate("app.title"))
        apply_app_icon(self)
        self.setMinimumSize(_MAIN_WINDOW_MIN_WIDTH, _MAIN_WINDOW_MIN_HEIGHT)
        self.resize(_MAIN_WINDOW_DEFAULT_WIDTH, _MAIN_WINDOW_DEFAULT_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        central_widget = QWidget()
        central_widget.setObjectName("ContentShell")
        central_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setCentralWidget(central_widget)

        shell = QHBoxLayout(central_widget)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        # Do not let layout size-hints re-lock the top-level window.
        shell.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        self.sidebar = NavSidebar()
        shell.addWidget(self.sidebar, 0)

        content = QFrame()
        content.setObjectName("ContentShell")
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabBar().setVisible(False)
        self.tab_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        content_layout.addWidget(self.tab_widget, 1)
        shell.addWidget(content, 1)

        self.dashboard = DashboardWidget(self.connections)
        self.connections_widget = ConnectionsWidget(self.connections)
        self.query_widget = QueryWidget(self.connections)
        self.backups_widget = BackupsWidget(self.connections)
        self.monitoring_widget = MonitoringWidget(self.connections)
        self.plugins_widget = PluginsWidget()
        self.settings_widget = SettingsWidget()

        self.settings_widget.theme_changed.connect(self._on_theme_changed)
        self.settings_widget.language_changed.connect(self._on_language_changed)
        self.settings_widget.users_admin.users_changed.connect(self.apply_rbac)
        self.settings_widget.settings_saved.connect(self._on_settings_saved)
        self.settings_widget.updates_panel.update_available.connect(
            self._on_update_available
        )

        self.tab_widget.addTab(self.dashboard, "")
        self.tab_widget.addTab(self.connections_widget, "")
        self.tab_widget.addTab(self.query_widget, "")
        self.tab_widget.addTab(self.backups_widget, "")
        self.tab_widget.addTab(self.monitoring_widget, "")
        self.tab_widget.addTab(self.plugins_widget, "")
        self.tab_widget.addTab(self.settings_widget, "")

        self._nav_keys = [
            "dashboard",
            "connections",
            "query",
            "backups",
            "monitoring",
            "plugins",
            "settings",
        ]
        self.sidebar.set_items([(k, "") for k in self._nav_keys])
        self.sidebar.navigated.connect(self._on_sidebar_navigated)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self._update_tabs()

        self.connections_widget.connection_added.connect(self._on_connection_added)
        self.connections_widget.connection_updated.connect(self._on_connection_updated)
        self.connections_widget.connection_deleted.connect(self._on_connection_deleted)

        self._create_menu_bar()

        self.tray: Optional[AppTray] = None
        self._quitting = False
        self._setup_tray()

        self._apply_theme()
        self.apply_rbac()
        # Monitoring users get live alerts without clicking Start (opt-in in Settings).
        QTimer.singleShot(0, self.monitoring_widget.autostart_if_configured)
        # Opt-in update check (default off, rate-limited, never installs).
        QTimer.singleShot(1500, self.settings_widget.updates_panel.maybe_auto_check)

    def _on_settings_saved(self) -> None:
        """Settings changed: re-read SMTP / S3 / experimental flags elsewhere."""
        self.monitoring_widget.refresh_email_channel()
        self.monitoring_widget.refresh_http_channels()
        if hasattr(self.backups_widget, "refresh_destinations"):
            self.backups_widget.refresh_destinations()

    def _setup_tray(self) -> None:
        """Left click toggles the window; right click opens the tray menu."""
        if not AppTray.is_available():
            return
        seconds = clamp_notification_seconds(
            self.secure_store.get_settings().get("notification_timeout_seconds")
        )
        self.tray = AppTray(
            self,
            timeout_seconds=seconds,
            status_provider=self._tray_status,
            open_section=self.show_section,
            open_changelog=self.show_changelog,
            open_check_updates=lambda: self.show_updates(check=True),
        )
        self.tray.quit_requested.connect(self._quit_app)
        self.settings_widget.notification_timeout_changed.connect(
            self.tray.set_timeout_seconds
        )
        self.monitoring_widget.attach_tray(self.tray)
        self.tray.show()

    def _tray_status(self):
        return (
            self.monitoring_widget.status_summary(),
            self.backups_widget.status_summary(),
        )

    def show_section(self, key: str) -> None:
        """Navigate to a nav section by key (tray / menu helpers)."""
        if key in self._nav_keys:
            self.tab_widget.setCurrentIndex(self._nav_keys.index(key))

    def show_updates(self, check: bool = False) -> None:
        """Open Settings → Updates. ``check`` runs the GitHub comparison."""
        self.show_section("settings")
        self.settings_widget.open_updates_tab(check=check)

    def show_changelog(self) -> None:
        """Open the changelog window. It does not contact GitHub."""
        from .changelog import ChangelogDialog

        ChangelogDialog(self).exec()

    def _on_update_available(self, message: str) -> None:
        """Tray notice only after an opted-in check finds a newer release."""
        if self.tray is None or not message:
            return
        self.tray.notify(
            self.i18n.translate("updates.check", default="Check for updates"),
            message,
            "info",
        )

    def _quit_app(self) -> None:
        """Quit from the tray menu. Closing the window only hides it."""
        self._quitting = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def apply_rbac(self) -> None:
        """Refresh permission-gated controls after login / user changes."""
        auth = get_auth_manager()
        if hasattr(self.connections_widget, "apply_rbac"):
            self.connections_widget.apply_rbac()
        if hasattr(self.plugins_widget, "apply_rbac"):
            self.plugins_widget.apply_rbac()
        if hasattr(self.backups_widget, "apply_rbac"):
            self.backups_widget.apply_rbac()
        for widget in (self.monitoring_widget, self.query_widget):
            if hasattr(widget, "apply_rbac"):
                widget.apply_rbac()
        if hasattr(self.settings_widget, "apply_rbac"):
            self.settings_widget.apply_rbac()
        # Single sign-in indicator: the sidebar footer (no duplicate status bar).
        if auth.is_rbac_active() and auth.current_user:
            self.sidebar.set_footer(
                self.i18n.translate(
                    "auth.signed_in",
                    default="Signed in as {user} ({role})",
                    user=auth.current_user.username,
                    role=auth.current_user.role.value,
                )
            )
        elif auth.is_rbac_active():
            self.sidebar.set_footer(
                self.i18n.translate(
                    "auth.rbac_active",
                    default="RBAC active — sign in required for sensitive actions",
                )
            )
        else:
            self.sidebar.set_footer(
                self.i18n.translate("common.ready", default="Ready")
            )

    def _create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        menubar.clear()

        t = self.i18n.translate

        file_menu = menubar.addMenu(t("menu.file"))
        exit_action = QAction(t("menu.exit"), self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu(t("menu.view"))
        targets = [
            (t("menu.dashboard"), "Ctrl+1", 0),
            (t("menu.connections"), "Ctrl+2", 1),
            (t("menu.query_console"), "Ctrl+3", 2),
            (t("menu.backups"), "Ctrl+4", 3),
            (t("menu.monitoring"), "Ctrl+5", 4),
            (t("menu.plugins", default="&Plugins"), "Ctrl+6", 5),
            (t("tabs.settings", default="&Settings"), "Ctrl+7", 6),
        ]
        for label, shortcut, index in targets:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(
                lambda _checked=False, i=index: self.tab_widget.setCurrentIndex(i)
            )
            view_menu.addAction(action)

        help_menu = menubar.addMenu(t("menu.help"))
        about_action = QAction(t("menu.about"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        changelog_action = QAction(
            t("menu.changelog", default="Changelog"), self
        )
        changelog_action.triggered.connect(self.show_changelog)
        help_menu.addAction(changelog_action)
        check_action = QAction(
            t("menu.check_updates", default="Check for updates"), self
        )
        check_action.triggered.connect(lambda: self.show_updates(check=True))
        help_menu.addAction(check_action)

    def _show_about(self):
        """Show the About window."""
        from .about import AboutDialog

        AboutDialog(
            self,
            on_check_updates=lambda: self.show_updates(check=True),
        ).exec()

    def _update_tabs(self):
        """Update tab / sidebar labels with translations"""
        t = self.i18n.translate
        labels = [
            t("tabs.dashboard"),
            t("tabs.connections"),
            t("tabs.query_console"),
            t("tabs.backups"),
            t("tabs.monitoring", default="Monitoring"),
            t("tabs.plugins", default="Plugins"),
            t("tabs.settings"),
        ]
        for i, label in enumerate(labels):
            self.tab_widget.setTabText(i, label)
        self.sidebar.set_labels(labels)
        self.sidebar.set_section_label(
            t("nav.workspace", default="Workspace")
        )
        self.sidebar.brand.setText(t("app.title", default="DB Storage Manager"))
        self.sidebar.caption.setText(t("app.vendor", default="VOXHASH LABS"))
        if getattr(self, "tray", None) is not None:
            self.tray.retranslate()

    def _on_sidebar_navigated(self, index: int) -> None:
        if self._syncing_nav:
            return
        self._syncing_nav = True
        try:
            self.tab_widget.setCurrentIndex(index)
        finally:
            self._syncing_nav = False

    def _on_tab_changed(self, index: int) -> None:
        if self._syncing_nav:
            return
        self._syncing_nav = True
        try:
            self.sidebar.set_current_index(index)
        finally:
            self._syncing_nav = False

    def _apply_theme(self):
        """Apply theme to application and refresh glass panel stylesheets."""
        apply_theme_to_app(self)
        # Stroke icons are painted with token colours: repaint on theme switch.
        refresh_icons(self)
        # Tab-local glass stylesheets embed token colors; re-apply so Atmospheric /
        # Light / Dracula switches do not leave stale MetricCard / PageTitle ink.
        for panel in self.findChildren(QWidget, "glassmorphism"):
            apply_glassmorphism(panel)
        # Table cells carry per-item colours (Enabled column): rebuild with the new tokens.
        if hasattr(self, "plugins_widget"):
            self.plugins_widget.refresh()

    def _on_theme_changed(self, theme_key):
        """Handle theme change"""
        self._apply_theme()
        self._create_menu_bar()

    def _on_language_changed(self, lang_code):
        """Handle language change"""
        self.setWindowTitle(self.i18n.translate("app.title"))
        self._create_menu_bar()
        self._update_tabs()
        self.apply_rbac()

    def _on_connection_added(self, connection):
        """Handle connection added"""
        self.connections.append(connection)
        self.secure_store.save_connections(self.connections)
        self.secure_store.upsert_ssh_settings_for_connection(connection)
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)
        self.monitoring_widget.update_connections(self.connections)

    def _on_connection_updated(self, connection):
        """Handle connection updated"""
        for i, conn in enumerate(self.connections):
            if conn["id"] == connection["id"]:
                self.connections[i] = connection
                break
        self.secure_store.save_connections(self.connections)
        # A pooled session keyed by this id still points at the old settings
        # (host / database path); drop it so backups and restores hit the new target.
        try:
            import asyncio
            from ..db.factory import DatabaseConnectionFactory

            asyncio.run(
                DatabaseConnectionFactory.get_pool().discard_key(connection["id"])
            )
        except Exception:
            pass
        if connection.get("ssh_config") and connection["ssh_config"].get("enabled"):
            self.secure_store.upsert_ssh_settings_for_connection(connection)
        else:
            self.secure_store.remove_ssh_settings_for_connection(connection["id"])
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)
        self.monitoring_widget.update_connections(self.connections)

    def _on_connection_deleted(self, connection_id):
        """Handle connection deleted"""
        self.connections = [c for c in self.connections if c["id"] != connection_id]
        self.secure_store.save_connections(self.connections)
        self.secure_store.remove_ssh_settings_for_connection(connection_id)
        try:
            import asyncio
            from ..db.factory import DatabaseConnectionFactory

            asyncio.run(DatabaseConnectionFactory.get_pool().discard_key(connection_id))
        except Exception:
            pass
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)
        self.monitoring_widget.update_connections(self.connections)

    def closeEvent(self, event):
        """Hide to the tray. Quit (tray menu) shuts tunnels and the pool down."""
        tray = getattr(self, "tray", None)
        if tray is not None and not getattr(self, "_quitting", False):
            event.ignore()
            self.hide()
            try:
                tray.refresh_status()
            except Exception:
                pass
            return
        try:
            self.connections_widget.close_all_tunnels()
        except Exception:
            pass
        for widget in (self.backups_widget, self.monitoring_widget):
            try:
                widget.shutdown()
            except Exception:
                pass
        if self.tray is not None:
            self.tray.hide()
        try:
            from ..db.factory import DatabaseConnectionFactory

            DatabaseConnectionFactory.shutdown_pool_blocking()
        except Exception:
            pass
        super().closeEvent(event)
