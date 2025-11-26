"""
Dashboard widget for displaying database storage analysis
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import asyncio

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism


class AnalysisWorker(QThread):
    """Worker thread for database analysis"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, connection_config):
        super().__init__()
        self.connection_config = connection_config

    def run(self):
        """Run analysis in thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            config = ConnectionConfig(**self.connection_config)
            db = DatabaseConnectionFactory.create_connection(config)

            async def analyze():
                await db.connect()
                analysis = await db.analyze_storage()
                await db.disconnect()
                return analysis

            result = loop.run_until_complete(analyze())
            loop.close()

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class DashboardWidget(QWidget):
    """Dashboard widget"""

    def __init__(self, connections):
        super().__init__()
        self.connections = connections
        self.current_analysis = None
        self.i18n = get_i18n_manager()
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Connection selection
        connection_layout = QHBoxLayout()
        t = self.i18n.translate
        connection_layout.addWidget(QLabel(f"{t('dashboard.connection')}"))
        self.connection_combo = QComboBox()
        self.connection_combo.addItem(t("dashboard.select_connection"))
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        self.connection_combo.currentIndexChanged.connect(self._on_connection_changed)
        connection_layout.addWidget(self.connection_combo)

        self.analyze_button = QPushButton(t("dashboard.analyze"))
        self.analyze_button.clicked.connect(self._analyze_database)
        connection_layout.addWidget(self.analyze_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        # Summary cards
        summary_layout = QHBoxLayout()
        self.total_size_label = QLabel(f"{t('dashboard.total_size', size='N/A')}")
        self.table_count_label = QLabel(f"{t('dashboard.tables', count='N/A')}")
        self.index_count_label = QLabel(f"{t('dashboard.indexes', count='N/A')}")
        summary_layout.addWidget(self.total_size_label)
        summary_layout.addWidget(self.table_count_label)
        summary_layout.addWidget(self.index_count_label)
        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        # Tables table
        self.tables_table = QTableWidget()
        self.tables_table.setColumnCount(5)
        self.tables_table.setHorizontalHeaderLabels(
            [
                t("dashboard.table_name"),
                t("dashboard.table_size"),
                t("dashboard.table_rows"),
                t("dashboard.table_index_size"),
                t("dashboard.table_bloat"),
            ]
        )
        self.tables_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.tables_table)

    def _on_connection_changed(self, index):
        """Handle connection selection change"""
        if index > 0:
            self.analyze_button.setEnabled(True)
        else:
            self.analyze_button.setEnabled(False)

    def _analyze_database(self):
        """Analyze selected database"""
        index = self.connection_combo.currentIndex()
        if index <= 0:
            return

        connection = self.connection_combo.itemData(index)
        if not connection:
            return

        self.analyze_button.setEnabled(False)
        self.analyze_button.setText(self.i18n.translate("dashboard.analyzing"))

        # Create worker thread
        self.worker = AnalysisWorker(connection)
        self.worker.finished.connect(self._on_analysis_finished)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.start()

    def _on_analysis_finished(self, analysis):
        """Handle analysis completion"""
        self.current_analysis = analysis
        self._update_display(analysis)
        self.analyze_button.setEnabled(True)
        self.analyze_button.setText(self.i18n.translate("dashboard.analyze"))

    def _on_analysis_error(self, error):
        """Handle analysis error"""
        t = self.i18n.translate
        QMessageBox.critical(
            self, t("common.error"), f"{t('dashboard.analysis_failed')}:\n{error}"
        )
        self.analyze_button.setEnabled(True)
        self.analyze_button.setText(t("dashboard.analyze"))

    def _update_display(self, analysis):
        """Update display with analysis results"""
        t = self.i18n.translate
        # Update summary
        total_size = analysis.get("totalSize", 0)
        self.total_size_label.setText(
            t("dashboard.total_size", size=self._format_size(total_size))
        )
        self.table_count_label.setText(
            t("dashboard.tables", count=analysis.get("tableCount", 0))
        )
        self.index_count_label.setText(
            t("dashboard.indexes", count=analysis.get("indexCount", 0))
        )

        # Update tables table
        tables = analysis.get("tables", [])
        self.tables_table.setRowCount(len(tables))

        for row, table in enumerate(tables):
            self.tables_table.setItem(row, 0, QTableWidgetItem(table["name"]))
            self.tables_table.setItem(
                row, 1, QTableWidgetItem(self._format_size(table["size"]))
            )
            self.tables_table.setItem(row, 2, QTableWidgetItem(str(table["rowCount"])))
            self.tables_table.setItem(
                row, 3, QTableWidgetItem(self._format_size(table["indexSize"]))
            )
            self.tables_table.setItem(
                row, 4, QTableWidgetItem(f"{table['bloat']:.2f}%")
            )

    def _format_size(self, size_bytes):
        """Format size in bytes to human-readable format"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        self.connection_combo.clear()
        self.connection_combo.addItem(
            self.i18n.translate("dashboard.select_connection")
        )
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
