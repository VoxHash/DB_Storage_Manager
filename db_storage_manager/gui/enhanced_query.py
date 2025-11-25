"""
Enhanced query console with templates, auto-completion, and visualization
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QCheckBox,
    QMenu, QAction, QListWidget, QSplitter, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism
from .charts import BarChartWidget, PieChartWidget


class SQLHighlighter(QSyntaxHighlighter):
    """SQL syntax highlighter"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []
        
        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(86, 156, 214))
        keyword_format.setFontWeight(700)
        keywords = [
            "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE",
            "CREATE", "DROP", "ALTER", "TABLE", "INDEX", "DATABASE",
            "JOIN", "INNER", "LEFT", "RIGHT", "OUTER", "ON", "AS",
            "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET",
            "AND", "OR", "NOT", "IN", "LIKE", "BETWEEN", "IS", "NULL",
        ]
        for keyword in keywords:
            pattern = f"\\b{keyword}\\b"
            self.highlighting_rules.append((pattern, keyword_format))
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor(206, 145, 120))
        self.highlighting_rules.append(("'[^']*'", string_format))
        self.highlighting_rules.append(('"[^"]*"', string_format))
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor(106, 153, 85))
        self.highlighting_rules.append(("--[^\n]*", comment_format))

    def highlightBlock(self, text):
        """Highlight a block of text"""
        for pattern, format in self.highlighting_rules:
            import re
            for match in re.finditer(pattern, text, re.IGNORECASE):
                self.setFormat(match.start(), match.end() - match.start(), format)


class QueryTemplates:
    """Query templates"""

    TEMPLATES = {
        "Select All": "SELECT * FROM {table} LIMIT 100;",
        "Count Rows": "SELECT COUNT(*) FROM {table};",
        "Find Large Tables": """
            SELECT 
                table_name,
                pg_size_pretty(pg_total_relation_size('"' || table_schema || '"."' || table_name || '"')) AS size
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY pg_total_relation_size('"' || table_schema || '"."' || table_name || '"') DESC
            LIMIT 10;
        """,
        "List Tables": "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';",
        "Table Info": """
            SELECT 
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_name = '{table}';
        """,
    }


class EnhancedQueryWidget(QWidget):
    """Enhanced query console"""

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

        # Toolbar
        toolbar = QHBoxLayout()
        
        # Connection selection
        toolbar.addWidget(QLabel(f"{t('query.connection')}"))
        self.connection_combo = QComboBox()
        self.connection_combo.addItem(t("query.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        toolbar.addWidget(self.connection_combo)
        
        # Templates
        self.template_combo = QComboBox()
        self.template_combo.addItems(list(QueryTemplates.TEMPLATES.keys()))
        self.template_combo.currentTextChanged.connect(self._load_template)
        toolbar.addWidget(QLabel("Template:"))
        toolbar.addWidget(self.template_combo)
        
        self.safe_mode_check = QCheckBox(t("query.safe_mode"))
        self.safe_mode_check.setChecked(True)
        toolbar.addWidget(self.safe_mode_check)
        
        self.execute_button = QPushButton(t("query.execute"))
        self.execute_button.clicked.connect(self._execute_query)
        toolbar.addWidget(self.execute_button)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Splitter for query editor and results
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Query editor with syntax highlighting
        self.query_edit = QTextEdit()
        self.query_edit.setPlaceholderText(t("query.query_placeholder"))
        self.highlighter = SQLHighlighter(self.query_edit.document())
        splitter.addWidget(self.query_edit)
        
        # Results area with tabs
        results_tabs = QTabWidget()
        
        # Table view
        self.results_table = QTableWidget()
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        results_tabs.addTab(self.results_table, "Table")
        
        # Chart view
        self.chart_widget = BarChartWidget("Query Results")
        results_tabs.addTab(self.chart_widget, "Chart")
        
        splitter.addWidget(results_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)

    def _load_template(self, template_name: str):
        """Load a query template"""
        template = QueryTemplates.TEMPLATES.get(template_name, "")
        self.query_edit.setPlainText(template)

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

        # Update table
        self.results_table.setColumnCount(len(columns))
        self.results_table.setHorizontalHeaderLabels(columns)
        self.results_table.setRowCount(len(rows))

        for row_idx, row_data in enumerate(rows):
            for col_idx, col_name in enumerate(columns):
                value = row_data.get(col_name, "")
                self.results_table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))

        # Update chart if numeric data
        if len(columns) >= 2 and rows:
            try:
                # Try to create a chart from first two columns
                x_values = [str(row.get(columns[0], "")) for row in rows[:10]]
                y_values = []
                for row in rows[:10]:
                    val = row.get(columns[1], 0)
                    try:
                        y_values.append(float(val))
                    except (ValueError, TypeError):
                        y_values.append(0)
                
                if y_values:
                    self.chart_widget = BarChartWidget("Query Results", x_values)
                    self.chart_widget.add_data_set(columns[1], y_values)
            except Exception:
                pass

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

