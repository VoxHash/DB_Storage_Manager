"""
Query console widget
"""

import asyncio

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
    QSplitter,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ..analysis.query_suggestions import suggest_for_query
from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from .utils import (
    apply_glassmorphism,
    apply_page_layout,
    configure_dense_table,
    make_page_header,
)

_SEVERITY_COLORS = {
    "high": QColor(220, 80, 80),
    "medium": QColor(220, 160, 60),
    "low": QColor(80, 140, 220),
    "info": QColor(120, 120, 120),
}


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
        apply_page_layout(layout)
        t = self.i18n.translate

        layout.addWidget(
            make_page_header(
                t("tabs.query_console"),
                t(
                    "query.page_subtitle",
                    default="Run SELECT-friendly queries with Safe Mode and Analyze",
                ),
            )
        )

        # Connection selection
        connection_layout = QHBoxLayout()
        connection_layout.setSpacing(8)
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
        self.execute_button.setObjectName("PrimaryButton")
        self.execute_button.clicked.connect(self._execute_query)
        connection_layout.addWidget(self.execute_button)

        self.analyze_button = QPushButton(t("query.analyze"))
        self.analyze_button.clicked.connect(self._analyze_query)
        connection_layout.addWidget(self.analyze_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Query editor
        self.query_edit = QTextEdit()
        self.query_edit.setPlaceholderText(t("query.query_placeholder"))
        splitter.addWidget(self.query_edit)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        configure_dense_table(self.results_table)
        splitter.addWidget(self.results_table)

        # Optimization suggestions
        suggestions_panel = QWidget()
        suggestions_layout = QVBoxLayout(suggestions_panel)
        suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestions_label = QLabel(t("query.suggestions_title"))
        suggestions_layout.addWidget(self.suggestions_label)

        self.suggestions_table = QTableWidget()
        self.suggestions_table.setColumnCount(4)
        self.suggestions_table.setHorizontalHeaderLabels(
            [
                t("query.suggestion_severity"),
                t("query.suggestion_title"),
                t("query.suggestion_message"),
                t("query.suggestion_source"),
            ]
        )
        self.suggestions_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.suggestions_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.suggestions_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.suggestions_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.suggestions_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.suggestions_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        configure_dense_table(self.suggestions_table)
        suggestions_layout.addWidget(self.suggestions_table)
        splitter.addWidget(suggestions_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        layout.addWidget(splitter)

    def _selected_connection(self):
        index = self.connection_combo.currentIndex()
        if index <= 0:
            return None
        return self.connection_combo.itemData(index)

    def _execute_query(self):
        """Execute query"""
        connection = self._selected_connection()
        if not connection:
            return

        query = self.query_edit.toPlainText()
        if not query.strip():
            return

        safe_mode = self.safe_mode_check.isChecked()

        try:
            config = ConnectionConfig(**connection)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def execute():
                db = await DatabaseConnectionFactory.acquire(config)
                try:
                    result = await db.execute_query(query, safe_mode)
                    advice = await suggest_for_query(
                        query,
                        connection=db,
                        explain_plan=result.get("explainPlan"),
                        safe_mode=safe_mode,
                        db_type=config.type,
                    )
                    return result, advice
                finally:
                    await DatabaseConnectionFactory.release(db)

            result, advice = loop.run_until_complete(execute())
            loop.close()

            self._display_results(result)
            self._display_suggestions(advice)
        except Exception as e:
            self._display_error(str(e))

    def _analyze_query(self):
        """Run optimization analysis without executing the user query."""
        query = self.query_edit.toPlainText()
        if not query.strip():
            self._display_suggestions(
                {
                    "suggestions": [],
                    "counts": {"total": 0},
                    "explainSkippedSafeMode": False,
                    "explainError": None,
                }
            )
            self.suggestions_label.setText(
                self.i18n.translate("query.suggestions_empty_query")
            )
            return

        connection = self._selected_connection()
        safe_mode = self.safe_mode_check.isChecked()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def analyze():
                db = None
                db_type = None
                if connection:
                    config = ConnectionConfig(**connection)
                    db_type = config.type
                    db = await DatabaseConnectionFactory.acquire(config)
                try:
                    return await suggest_for_query(
                        query,
                        connection=db,
                        safe_mode=safe_mode,
                        db_type=db_type,
                    )
                finally:
                    if db is not None:
                        await DatabaseConnectionFactory.release(db)

            advice = loop.run_until_complete(analyze())
            loop.close()
            self._display_suggestions(advice)
        except Exception as e:
            self._display_suggestions(
                {
                    "suggestions": [
                        {
                            "code": "analyze_error",
                            "severity": "info",
                            "title": self.i18n.translate("common.error"),
                            "message": str(e),
                            "source": "explain",
                        }
                    ],
                    "counts": {"total": 1},
                    "explainError": str(e),
                    "explainSkippedSafeMode": False,
                }
            )

    def _display_suggestions(self, advice: dict):
        """Populate the suggestions table from advisor output."""
        t = self.i18n.translate
        suggestions = advice.get("suggestions") or []
        counts = advice.get("counts") or {}
        total = counts.get("total", len(suggestions))

        status_bits = [t("query.suggestions_count").format(count=total)]
        if advice.get("explainSkippedSafeMode"):
            status_bits.append(t("query.suggestions_explain_skipped_safe"))
        if advice.get("explainError"):
            status_bits.append(
                t("query.suggestions_explain_error").format(
                    error=advice["explainError"]
                )
            )
        self.suggestions_label.setText(" — ".join(status_bits))

        self.suggestions_table.setRowCount(len(suggestions))
        for row_idx, item in enumerate(suggestions):
            severity = str(item.get("severity", "info"))
            cells = [
                severity,
                str(item.get("title", "")),
                str(item.get("message", "")),
                str(item.get("source", "")),
            ]
            color = _SEVERITY_COLORS.get(severity.lower())
            for col_idx, value in enumerate(cells):
                table_item = QTableWidgetItem(value)
                if color is not None and col_idx == 0:
                    table_item.setForeground(color)
                self.suggestions_table.setItem(row_idx, col_idx, table_item)

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
