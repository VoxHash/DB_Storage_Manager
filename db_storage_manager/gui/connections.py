"""
Connections management widget
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
import uuid

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism


class ConnectionDialog(QDialog):
    """Dialog for adding/editing connections"""

    def __init__(self, connection=None, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(t("connections.add_dialog_title") if not connection else t("connections.edit_dialog_title"))
        self.setModal(True)
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QFormLayout(self)
        t = self.i18n.translate

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My Database")
        layout.addRow(f"{t('connections.name')}", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["postgresql", "mysql", "sqlite", "mongodb", "redis"])
        layout.addRow(f"{t('connections.type')}", self.type_combo)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        layout.addRow(f"{t('connections.host')}", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5432)
        layout.addRow(f"{t('connections.port')}", self.port_spin)

        self.database_edit = QLineEdit()
        layout.addRow(f"{t('connections.database')}", self.database_edit)

        self.username_edit = QLineEdit()
        layout.addRow(f"{t('connections.username')}", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(f"{t('connections.password')}", self.password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # Load connection data if editing
        if self.connection:
            self.name_edit.setText(self.connection.get("name", ""))
            index = self.type_combo.findText(self.connection.get("type", "postgresql"))
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.host_edit.setText(self.connection.get("host", ""))
            self.port_spin.setValue(self.connection.get("port", 5432))
            self.database_edit.setText(self.connection.get("database", ""))
            self.username_edit.setText(self.connection.get("username", ""))
            self.password_edit.setText(self.connection.get("password", ""))

    def get_connection(self):
        """Get connection data from form"""
        return {
            "id": self.connection.get("id") if self.connection else str(uuid.uuid4()),
            "name": self.name_edit.text(),
            "type": self.type_combo.currentText(),
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
        }


class ConnectionsWidget(QWidget):
    """Connections management widget"""

    connection_added = pyqtSignal(dict)
    connection_updated = pyqtSignal(dict)
    connection_deleted = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.connections = []
        self.i18n = get_i18n_manager()
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        t = self.i18n.translate

        # Buttons
        button_layout = QHBoxLayout()
        self.add_button = QPushButton(t("connections.add_connection"))
        self.add_button.clicked.connect(self._add_connection)
        button_layout.addWidget(self.add_button)

        self.edit_button = QPushButton(t("connections.edit"))
        self.edit_button.clicked.connect(self._edit_connection)
        self.edit_button.setEnabled(False)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton(t("connections.delete"))
        self.delete_button.clicked.connect(self._delete_connection)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        self.test_button = QPushButton(t("connections.test_connection"))
        self.test_button.clicked.connect(self._test_connection)
        self.test_button.setEnabled(False)
        button_layout.addWidget(self.test_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Connections table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            t("connections.name").rstrip(":"),
            t("connections.type").rstrip(":"),
            t("connections.host").rstrip(":"),
            t("connections.database").rstrip(":")
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

    def _on_selection_changed(self):
        """Handle table selection change"""
        has_selection = len(self.table.selectedRows()) > 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.test_button.setEnabled(has_selection)

    def _add_connection(self):
        """Add a new connection"""
        dialog = ConnectionDialog(parent=self)
        if dialog.exec():
            connection = dialog.get_connection()
            self.connections.append(connection)
            self._update_table()
            self.connection_added.emit(connection)

    def _edit_connection(self):
        """Edit selected connection"""
        row = self.table.currentRow()
        if row < 0:
            return

        connection = self.connections[row]
        dialog = ConnectionDialog(connection, parent=self)
        if dialog.exec():
            updated = dialog.get_connection()
            self.connections[row] = updated
            self._update_table()
            self.connection_updated.emit(updated)

    def _delete_connection(self):
        """Delete selected connection"""
        row = self.table.currentRow()
        if row < 0:
            return

        t = self.i18n.translate
        reply = QMessageBox.question(
            self,
            t("common.confirm"),
            t("connections.delete_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            connection_id = self.connections[row]["id"]
            del self.connections[row]
            self._update_table()
            self.connection_deleted.emit(connection_id)

    def _test_connection(self):
        """Test selected connection"""
        row = self.table.currentRow()
        if row < 0:
            return

        connection = self.connections[row]
        try:
            config = ConnectionConfig(**connection)
            db = DatabaseConnectionFactory.create_connection(config)

            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(db.test_connection())
            loop.close()

            t = self.i18n.translate
            if result:
                QMessageBox.information(self, t("common.success"), t("connections.test_success"))
            else:
                QMessageBox.warning(self, t("common.error"), t("connections.test_failed"))
        except Exception as e:
            t = self.i18n.translate
            QMessageBox.critical(self, t("common.error"), f"{t('errors.connection_failed')}:\n{str(e)}")

    def _update_table(self):
        """Update connections table"""
        self.table.setRowCount(len(self.connections))
        for row, conn in enumerate(self.connections):
            self.table.setItem(row, 0, QTableWidgetItem(conn.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(conn.get("type", "")))
            self.table.setItem(row, 2, QTableWidgetItem(conn.get("host", "")))
            self.table.setItem(row, 3, QTableWidgetItem(conn.get("database", "")))

