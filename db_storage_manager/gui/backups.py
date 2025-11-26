"""
Backups management widget
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QTabWidget,
)
from PyQt6.QtCore import Qt
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism


class BackupsWidget(QWidget):
    """Backups management widget"""

    def __init__(self, connections):
        super().__init__()
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        t = self.i18n.translate

        # Create tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Create Backup tab
        create_widget = QWidget()
        create_layout = QVBoxLayout(create_widget)
        create_layout.addWidget(QLabel(t("backups.create_backup")))
        tabs.addTab(create_widget, t("backups.create_backup"))

        # Restore Backup tab
        restore_widget = QWidget()
        restore_layout = QVBoxLayout(restore_widget)
        restore_layout.addWidget(QLabel(t("backups.restore_backup")))
        tabs.addTab(restore_widget, t("backups.restore_backup"))

        # Scheduled Backups tab
        scheduled_widget = QWidget()
        scheduled_layout = QVBoxLayout(scheduled_widget)
        scheduled_layout.addWidget(QLabel(t("backups.scheduled_backups")))
        tabs.addTab(scheduled_widget, t("backups.scheduled_backups"))

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
