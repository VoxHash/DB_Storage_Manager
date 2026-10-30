"""
Main application window — modern desktop shell with library-style navigation.
"""

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLayout,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
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
from .utils import apply_glassmorphism, apply_theme_to_app

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
        self.statusBar().showMessage(self.i18n.translate("common.ready"))

        self._apply_theme()
        self.apply_rbac()

    def apply_rbac(self) -> None:
        """Refresh permission-gated controls after login / user changes."""
        auth = get_auth_manager()
        if hasattr(self.connections_widget, "apply_rbac"):
            self.connections_widget.apply_rbac()
        if hasattr(self.plugins_widget, "apply_rbac"):
            self.plugins_widget.apply_rbac()
        if hasattr(self.backups_widget, "apply_rbac"):
            self.backups_widget.apply_rbac()
        if hasattr(self.settings_widget, "apply_rbac"):
            self.settings_widget.apply_rbac()
        if auth.is_rbac_active() and auth.current_user:
            self.statusBar().showMessage(
                self.i18n.translate(
                    "auth.signed_in",
                    default="Signed in as {user} ({role})",
                    user=auth.current_user.username,
                    role=auth.current_user.role.value,
                )
            )
            self.sidebar.set_footer(
                self.i18n.translate(
                    "auth.signed_in",
                    default="Signed in as {user} ({role})",
                    user=auth.current_user.username,
                    role=auth.current_user.role.value,
                )
            )
        elif auth.is_rbac_active():
            msg = self.i18n.translate(
                "auth.rbac_active",
                default="RBAC active — sign in required for sensitive actions",
            )
            self.statusBar().showMessage(msg)
            self.sidebar.set_footer(msg)
        else:
            self.statusBar().showMessage(self.i18n.translate("common.ready"))
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

    def _show_about(self):
        """Show about dialog"""
        t = self.i18n.translate
        QMessageBox.about(
            self,
            t("about.title"),
            f"{t('about.version')}\n\n"
            f"{t('about.description')}\n\n"
            f"{t('about.built_with')}\n\n"
            f"{t('about.copyright')}",
        )

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
        # Tab-local glass stylesheets embed token colors; re-apply so Atmospheric /
        # Light / Dracula switches do not leave stale MetricCard / PageTitle ink.
        for panel in self.findChildren(QWidget, "glassmorphism"):
            apply_glassmorphism(panel)

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
        """Ensure SSH tunnels and pooled SQL sessions close on shutdown."""
        try:
            self.connections_widget.close_all_tunnels()
        except Exception:
            pass
        try:
            from ..db.factory import DatabaseConnectionFactory

            DatabaseConnectionFactory.shutdown_pool_blocking()
        except Exception:
            pass
        super().closeEvent(event)
