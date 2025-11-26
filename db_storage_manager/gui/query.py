"""
Query console widget
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QCheckBox,
)
from PyQt6.QtCore import Qt

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism


class QueryWidget(QWidget):
    """Query console widget"""

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

        # Connection selection
        connection_layout = QHBoxLayout()
        connection_layout.addWidget(QLabel(f"{t('query.connection')}"))
        self.connection_combo = QComboBox()
        self.connection_combo.addItem(t("query.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        connection_layout.addWidget(self.connection_combo)

        self.safe_mode_check = QCheckBox(t("query.safe_mode"))
        self.safe_mode_check.setChecked(True)
        connection_layout.addWidget(self.safe_mode_check)

        self.execute_button = QPushButton(t("query.execute"))
        self.execute_button.clicked.connect(self._execute_query)
        connection_layout.addWidget(self.execute_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        # Query editor
        self.query_edit = QTextEdit()
        self.query_edit.setPlaceholderText(t("query.query_placeholder"))
        layout.addWidget(self.query_edit)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.results_table)

    def _execute_query(self):
        """Execute query"""
        index = self.connection_combo.currentIndex()
        if index <= 0:
            return

        connection = self.connection_combo.itemData(index)
        if not connection:
            return

        query = self.query_edit.toPlainText()
        if not query.strip():
            return

        safe_mode = self.safe_mode_check.isChecked()

        try:
            config = ConnectionConfig(**connection)
            db = DatabaseConnectionFactory.create_connection(config)

            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def execute():
                await db.connect()
                result = await db.execute_query(query, safe_mode)
                await db.disconnect()
                return result

            result = loop.run_until_complete(execute())
            loop.close()

            # Display results
            self._display_results(result)
        except Exception as e:
            self._display_error(str(e))

    def _display_results(self, result):
        """Display query results"""
        columns = result.get("columns", [])
        rows = result.get("rows", [])

        self.results_table.setColumnCount(len(columns))
        self.results_table.setHorizontalHeaderLabels(columns)
        self.results_table.setRowCount(len(rows))

        for row_idx, row_data in enumerate(rows):
            for col_idx, col_name in enumerate(columns):
                value = row_data.get(col_name, "")
                self.results_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(str(value))
                )

    def _display_error(self, error):
        """Display error message"""
        t = self.i18n.translate
        self.results_table.setColumnCount(1)
        self.results_table.setHorizontalHeaderLabels([t("common.error")])
        self.results_table.setRowCount(1)
        self.results_table.setItem(0, 0, QTableWidgetItem(error))

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        self.connection_combo.clear()
        self.connection_combo.addItem(self.i18n.translate("query.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
