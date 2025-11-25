"""
Main application window
"""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QMessageBox,
)
from PyQt6.QtGui import QAction

from .dashboard import DashboardWidget
from .connections import ConnectionsWidget
from .query import QueryWidget
from .backups import BackupsWidget
from .settings import SettingsWidget
from ..security.store import SecureStore
from ..i18n.manager import get_i18n_manager
from ..themes.manager import get_theme_manager
from .utils import apply_theme_to_app


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.secure_store = SecureStore()
        self.i18n = get_i18n_manager()
        self.theme_manager = get_theme_manager()
        self.connections = self.secure_store.get_connections()

        self.setWindowTitle(self.i18n.translate("app.title"))
        self.setMinimumSize(1200, 800)

        # Create central widget with tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Create tabs
        self.dashboard = DashboardWidget(self.connections)
        self.connections_widget = ConnectionsWidget()
        self.query_widget = QueryWidget(self.connections)
        self.backups_widget = BackupsWidget(self.connections)
        self.settings_widget = SettingsWidget()

        # Connect settings widget signals
        self.settings_widget.theme_changed.connect(self._on_theme_changed)
        self.settings_widget.language_changed.connect(self._on_language_changed)

        # Add tabs to tab widget
        self.tab_widget.addTab(self.dashboard, "")
        self.tab_widget.addTab(self.connections_widget, "")
        self.tab_widget.addTab(self.query_widget, "")
        self.tab_widget.addTab(self.backups_widget, "")
        self.tab_widget.addTab(self.settings_widget, "")

        self._update_tabs()

        # Connect connections widget to update other widgets
        self.connections_widget.connection_added.connect(self._on_connection_added)
        self.connections_widget.connection_updated.connect(self._on_connection_updated)
        self.connections_widget.connection_deleted.connect(self._on_connection_deleted)

        # Create menu bar
        self._create_menu_bar()

        # Create status bar
        self.statusBar().showMessage(self.i18n.translate("common.ready"))

        # Apply theme
        self._apply_theme()
        
        # Apply background to central widget
        self._apply_central_widget_style()

    def _create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        
        # Clear all existing menus to prevent duplicates
        menubar.clear()
        
        t = self.i18n.translate

        # File menu
        file_menu = menubar.addMenu(t("menu.file"))
        exit_action = QAction(t("menu.exit"), self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu(t("menu.view"))
        dashboard_action = QAction(t("menu.dashboard"), self)
        dashboard_action.setShortcut("Ctrl+1")
        dashboard_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(0))
        view_menu.addAction(dashboard_action)

        connections_action = QAction(t("menu.connections"), self)
        connections_action.setShortcut("Ctrl+2")
        connections_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(1))
        view_menu.addAction(connections_action)

        query_action = QAction(t("menu.query_console"), self)
        query_action.setShortcut("Ctrl+3")
        query_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(2))
        view_menu.addAction(query_action)

        backups_action = QAction(t("menu.backups"), self)
        backups_action.setShortcut("Ctrl+4")
        backups_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(3))
        view_menu.addAction(backups_action)

        # Help menu
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
        """Update tab labels with translations"""
        t = self.i18n.translate
        self.tab_widget.setTabText(0, t("tabs.dashboard"))
        self.tab_widget.setTabText(1, t("tabs.connections"))
        self.tab_widget.setTabText(2, t("tabs.query_console"))
        self.tab_widget.setTabText(3, t("tabs.backups"))
        self.tab_widget.setTabText(4, t("tabs.settings"))

    def _apply_theme(self):
        """Apply theme to application"""
        apply_theme_to_app(self)
    
    def _apply_central_widget_style(self):
        """Apply proper styling to central widget"""
        from ..themes.manager import get_theme_manager
        theme_manager = get_theme_manager()
        theme = theme_manager.get_theme()
        colors = theme["colors"]
        
        central_widget = self.centralWidget()
        if central_widget:
            central_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {colors['background']};
                    color: {colors['text']};
                }}
            """)

    def _on_theme_changed(self, theme_key):
        """Handle theme change"""
        self._apply_theme()
        # Recreate menu bar to apply theme
        self._create_menu_bar()

    def _on_language_changed(self, lang_code):
        """Handle language change"""
        self.setWindowTitle(self.i18n.translate("app.title"))
        self._create_menu_bar()
        self._update_tabs()
        self.statusBar().showMessage(self.i18n.translate("common.ready"))

    def _on_connection_added(self, connection):
        """Handle connection added"""
        self.connections.append(connection)
        self.secure_store.save_connections(self.connections)
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)

    def _on_connection_updated(self, connection):
        """Handle connection updated"""
        for i, conn in enumerate(self.connections):
            if conn["id"] == connection["id"]:
                self.connections[i] = connection
                break
        self.secure_store.save_connections(self.connections)
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)

    def _on_connection_deleted(self, connection_id):
        """Handle connection deleted"""
        self.connections = [c for c in self.connections if c["id"] != connection_id]
        self.secure_store.save_connections(self.connections)
        self.dashboard.update_connections(self.connections)
        self.query_widget.update_connections(self.connections)
        self.backups_widget.update_connections(self.connections)

