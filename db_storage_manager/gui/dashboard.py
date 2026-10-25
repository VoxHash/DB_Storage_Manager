"""
Dashboard widget for displaying database storage analysis
with saved layouts and watched-metrics customization.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import DASHBOARD_COLUMN_KEYS, DASHBOARD_METRIC_KEYS
from ..dashboard_prefs import (
    apply_named_layout,
    delete_named_layout,
    normalize_dashboard_layout,
    save_named_layout,
)
from ..db.base import ConnectionConfig
from ..db.factory import DatabaseConnectionFactory
from ..i18n.manager import get_i18n_manager
from ..security.store import SecureStore
from .utils import apply_glassmorphism

_METRIC_I18N = {
    "total_size": "dashboard.metric_total_size",
    "tables": "dashboard.metric_tables",
    "indexes": "dashboard.metric_indexes",
}

_COLUMN_I18N = {
    "name": "dashboard.table_name",
    "size": "dashboard.table_size",
    "rows": "dashboard.table_rows",
    "index_size": "dashboard.table_index_size",
    "bloat": "dashboard.table_bloat",
}

_COLUMN_ANALYSIS_KEYS = {
    "name": "name",
    "size": "size",
    "rows": "rowCount",
    "index_size": "indexSize",
    "bloat": "bloat",
}


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
    """Dashboard widget with customizable watched metrics and saved layouts."""

    def __init__(self, connections):
        super().__init__()
        self.connections = connections
        self.current_analysis = None
        self.i18n = get_i18n_manager()
        self.secure_store = SecureStore()
        self.layout_prefs: Dict[str, Any] = normalize_dashboard_layout(None)
        self._metric_labels: Dict[str, QLabel] = {}
        self._metric_checks: Dict[str, QCheckBox] = {}
        self._column_checks: Dict[str, QCheckBox] = {}
        self._updating_prefs_ui = False
        self.setObjectName("glassmorphism")
        self.init_ui()
        self._load_layout_prefs()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

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
        self.analyze_button.setEnabled(False)
        connection_layout.addWidget(self.analyze_button)

        connection_layout.addStretch()
        layout.addLayout(connection_layout)

        self.summary_layout = QHBoxLayout()
        for key in DASHBOARD_METRIC_KEYS:
            label = QLabel(self._metric_placeholder(key))
            label.setObjectName(f"dashboardMetric_{key}")
            self._metric_labels[key] = label
            self.summary_layout.addWidget(label)
        self.summary_layout.addStretch()
        layout.addLayout(self.summary_layout)

        self.tables_table = QTableWidget()
        self.tables_table.setColumnCount(len(DASHBOARD_COLUMN_KEYS))
        self.tables_table.setHorizontalHeaderLabels(
            [t(_COLUMN_I18N[k]) for k in DASHBOARD_COLUMN_KEYS]
        )
        self.tables_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.tables_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.tables_table)

        customize = QGroupBox(t("dashboard.customize_title"))
        customize.setObjectName("dashboardCustomize")
        customize_layout = QVBoxLayout(customize)

        metrics_row = QHBoxLayout()
        metrics_row.addWidget(QLabel(t("dashboard.watched_metrics")))
        for key in DASHBOARD_METRIC_KEYS:
            check = QCheckBox(t(_METRIC_I18N[key]))
            check.setChecked(True)
            check.stateChanged.connect(self._on_prefs_checkbox_changed)
            self._metric_checks[key] = check
            metrics_row.addWidget(check)
        metrics_row.addStretch()
        customize_layout.addLayout(metrics_row)

        columns_row = QHBoxLayout()
        columns_row.addWidget(QLabel(t("dashboard.table_columns")))
        for key in DASHBOARD_COLUMN_KEYS:
            check = QCheckBox(t(_COLUMN_I18N[key]))
            check.setChecked(True)
            check.stateChanged.connect(self._on_prefs_checkbox_changed)
            self._column_checks[key] = check
            columns_row.addWidget(check)
        columns_row.addStretch()
        customize_layout.addLayout(columns_row)

        layouts_row = QHBoxLayout()
        layouts_row.addWidget(QLabel(t("dashboard.saved_layouts")))
        self.layout_combo = QComboBox()
        self.layout_combo.currentIndexChanged.connect(self._on_layout_combo_changed)
        layouts_row.addWidget(self.layout_combo)

        self.apply_layout_button = QPushButton(t("dashboard.apply_layout"))
        self.apply_layout_button.clicked.connect(self._apply_selected_layout)
        layouts_row.addWidget(self.apply_layout_button)

        self.save_layout_button = QPushButton(t("dashboard.save_layout"))
        self.save_layout_button.clicked.connect(self._save_current_layout)
        layouts_row.addWidget(self.save_layout_button)

        self.save_as_layout_button = QPushButton(t("dashboard.save_layout_as"))
        self.save_as_layout_button.clicked.connect(self._save_layout_as)
        layouts_row.addWidget(self.save_as_layout_button)

        self.delete_layout_button = QPushButton(t("dashboard.delete_layout"))
        self.delete_layout_button.clicked.connect(self._delete_selected_layout)
        layouts_row.addWidget(self.delete_layout_button)

        self.reset_layout_button = QPushButton(t("dashboard.reset_layout"))
        self.reset_layout_button.clicked.connect(self._reset_layout)
        layouts_row.addWidget(self.reset_layout_button)

        layouts_row.addStretch()
        customize_layout.addLayout(layouts_row)

        layout.addWidget(customize)

    def _metric_placeholder(self, key: str) -> str:
        t = self.i18n.translate
        if key == "total_size":
            return t("dashboard.total_size", size="N/A")
        if key == "tables":
            return t("dashboard.tables", count="N/A")
        return t("dashboard.indexes", count="N/A")

    def _load_layout_prefs(self) -> None:
        settings = self.secure_store.get_settings()
        self.layout_prefs = normalize_dashboard_layout(settings.get("dashboard_layout"))
        self._sync_prefs_ui_from_layout()
        self._apply_layout_to_display()
        self._restore_last_connection()

    def _persist_layout_prefs(self) -> None:
        settings = self.secure_store.get_settings()
        settings["dashboard_layout"] = normalize_dashboard_layout(self.layout_prefs)
        self.secure_store.set_settings(settings)
        self.layout_prefs = settings["dashboard_layout"]

    def _read_prefs_from_ui(self) -> None:
        watched = [
            key
            for key in DASHBOARD_METRIC_KEYS
            if self._metric_checks[key].isChecked()
        ]
        if not watched:
            # Keep at least one watched metric
            watched = ["total_size"]
            self._updating_prefs_ui = True
            self._metric_checks["total_size"].setChecked(True)
            self._updating_prefs_ui = False

        columns = [
            key
            for key in DASHBOARD_COLUMN_KEYS
            if self._column_checks[key].isChecked()
        ]
        if not columns:
            columns = ["name"]
            self._updating_prefs_ui = True
            self._column_checks["name"].setChecked(True)
            self._updating_prefs_ui = False

        # Preserve relative order from previous metric_order
        prev_order = self.layout_prefs.get("metric_order") or list(DASHBOARD_METRIC_KEYS)
        order = [m for m in prev_order if m in watched]
        for m in watched:
            if m not in order:
                order.append(m)

        self.layout_prefs["watched_metrics"] = watched
        self.layout_prefs["table_columns"] = columns
        self.layout_prefs["metric_order"] = order

    def _sync_prefs_ui_from_layout(self) -> None:
        self._updating_prefs_ui = True
        watched = set(self.layout_prefs.get("watched_metrics") or [])
        columns = set(self.layout_prefs.get("table_columns") or [])
        for key, check in self._metric_checks.items():
            check.setChecked(key in watched)
        for key, check in self._column_checks.items():
            check.setChecked(key in columns)

        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        saved = self.layout_prefs.get("saved_layouts") or {}
        for name in sorted(saved.keys(), key=lambda n: (n != "Default", n.lower())):
            self.layout_combo.addItem(name)
        active = self.layout_prefs.get("active_layout") or "Default"
        idx = self.layout_combo.findText(active)
        if idx >= 0:
            self.layout_combo.setCurrentIndex(idx)
        self.layout_combo.blockSignals(False)
        self.delete_layout_button.setEnabled(active != "Default")
        self._updating_prefs_ui = False

    def _apply_layout_to_display(self) -> None:
        order = self.layout_prefs.get("metric_order") or list(DASHBOARD_METRIC_KEYS)
        watched = set(self.layout_prefs.get("watched_metrics") or [])

        # Re-order summary labels to match metric_order
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        for key in order:
            label = self._metric_labels[key]
            label.setVisible(key in watched)
            self.summary_layout.addWidget(label)
        for key in DASHBOARD_METRIC_KEYS:
            if key not in order:
                label = self._metric_labels[key]
                label.setVisible(key in watched)
                self.summary_layout.addWidget(label)
        self.summary_layout.addStretch()

        visible_columns = self.layout_prefs.get("table_columns") or list(
            DASHBOARD_COLUMN_KEYS
        )
        for col_index, key in enumerate(DASHBOARD_COLUMN_KEYS):
            self.tables_table.setColumnHidden(col_index, key not in visible_columns)

        if self.current_analysis:
            self._update_display(self.current_analysis)

    def _restore_last_connection(self) -> None:
        last_id = self.layout_prefs.get("last_connection_id")
        if not last_id:
            return
        for i in range(1, self.connection_combo.count()):
            conn = self.connection_combo.itemData(i)
            if isinstance(conn, dict) and conn.get("id") == last_id:
                self.connection_combo.setCurrentIndex(i)
                return

    def _on_prefs_checkbox_changed(self, _state: int = 0) -> None:
        if self._updating_prefs_ui:
            return
        self._read_prefs_from_ui()
        self._apply_layout_to_display()
        self._persist_layout_prefs()

    def _on_layout_combo_changed(self, _index: int) -> None:
        if self._updating_prefs_ui:
            return
        name = self.layout_combo.currentText()
        self.delete_layout_button.setEnabled(bool(name) and name != "Default")

    def _apply_selected_layout(self) -> None:
        name = self.layout_combo.currentText()
        if not name:
            return
        try:
            self.layout_prefs = apply_named_layout(self.layout_prefs, name)
        except KeyError:
            QMessageBox.warning(
                self,
                self.i18n.translate("common.error"),
                self.i18n.translate("dashboard.layout_missing", name=name),
            )
            return
        self._sync_prefs_ui_from_layout()
        self._apply_layout_to_display()
        self._persist_layout_prefs()

    def _save_current_layout(self) -> None:
        self._read_prefs_from_ui()
        name = self.layout_prefs.get("active_layout") or "Default"
        self.layout_prefs = save_named_layout(self.layout_prefs, name)
        self._sync_prefs_ui_from_layout()
        self._persist_layout_prefs()
        QMessageBox.information(
            self,
            self.i18n.translate("common.success"),
            self.i18n.translate("dashboard.layout_saved", name=name),
        )

    def _save_layout_as(self) -> None:
        t = self.i18n.translate
        name, ok = QInputDialog.getText(
            self, t("dashboard.save_layout_as_title"), t("dashboard.layout_name_prompt")
        )
        if not ok or not name.strip():
            return
        self._read_prefs_from_ui()
        try:
            self.layout_prefs = save_named_layout(self.layout_prefs, name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return
        self._sync_prefs_ui_from_layout()
        self._apply_layout_to_display()
        self._persist_layout_prefs()
        QMessageBox.information(
            self,
            t("common.success"),
            t("dashboard.layout_saved", name=name.strip()),
        )

    def _delete_selected_layout(self) -> None:
        name = self.layout_combo.currentText()
        if not name or name == "Default":
            return
        t = self.i18n.translate
        reply = QMessageBox.question(
            self,
            t("dashboard.delete_layout"),
            t("dashboard.delete_layout_confirm", name=name),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.layout_prefs = delete_named_layout(self.layout_prefs, name)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, t("common.error"), str(exc))
            return
        self._sync_prefs_ui_from_layout()
        self._apply_layout_to_display()
        self._persist_layout_prefs()

    def _reset_layout(self) -> None:
        self.layout_prefs = apply_named_layout(
            normalize_dashboard_layout(None), "Default"
        )
        # Preserve last connection across reset
        settings = self.secure_store.get_settings()
        existing = normalize_dashboard_layout(settings.get("dashboard_layout"))
        self.layout_prefs["last_connection_id"] = existing.get("last_connection_id")
        # Keep any extra named layouts the user already saved
        saved = existing.get("saved_layouts") or {}
        self.layout_prefs["saved_layouts"] = {
            **saved,
            "Default": self.layout_prefs["saved_layouts"]["Default"],
        }
        self.layout_prefs = apply_named_layout(self.layout_prefs, "Default")
        self._sync_prefs_ui_from_layout()
        self._apply_layout_to_display()
        self._persist_layout_prefs()

    def _on_connection_changed(self, index):
        """Handle connection selection change"""
        if index > 0:
            self.analyze_button.setEnabled(True)
            conn = self.connection_combo.itemData(index)
            if isinstance(conn, dict) and conn.get("id"):
                self.layout_prefs["last_connection_id"] = conn["id"]
                self._persist_layout_prefs()
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
        total_size = analysis.get("totalSize", 0)
        self._metric_labels["total_size"].setText(
            t("dashboard.total_size", size=self._format_size(total_size))
        )
        self._metric_labels["tables"].setText(
            t("dashboard.tables", count=analysis.get("tableCount", 0))
        )
        self._metric_labels["indexes"].setText(
            t("dashboard.indexes", count=analysis.get("indexCount", 0))
        )

        tables = analysis.get("tables", [])
        self.tables_table.setRowCount(len(tables))

        for row, table in enumerate(tables):
            for col_index, key in enumerate(DASHBOARD_COLUMN_KEYS):
                analysis_key = _COLUMN_ANALYSIS_KEYS[key]
                value = table.get(analysis_key, "")
                if key in ("size", "index_size"):
                    text = self._format_size(value or 0)
                elif key == "bloat":
                    try:
                        text = f"{float(value):.2f}%"
                    except (TypeError, ValueError):
                        text = str(value)
                else:
                    text = str(value)
                self.tables_table.setItem(row, col_index, QTableWidgetItem(text))

        visible_columns = self.layout_prefs.get("table_columns") or list(
            DASHBOARD_COLUMN_KEYS
        )
        for col_index, key in enumerate(DASHBOARD_COLUMN_KEYS):
            self.tables_table.setColumnHidden(col_index, key not in visible_columns)

    def _format_size(self, size_bytes):
        """Format size in bytes to human-readable format"""
        size_bytes = float(size_bytes or 0)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def update_connections(self, connections):
        """Update connections list"""
        previous_id = None
        index = self.connection_combo.currentIndex()
        if index > 0:
            conn = self.connection_combo.itemData(index)
            if isinstance(conn, dict):
                previous_id = conn.get("id")
        if previous_id is None:
            previous_id = self.layout_prefs.get("last_connection_id")

        self.connections = connections
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        self.connection_combo.addItem(
            self.i18n.translate("dashboard.select_connection")
        )
        for conn in self.connections:
            self.connection_combo.addItem(conn["name"], conn)
        self.connection_combo.blockSignals(False)

        restored = False
        if previous_id:
            for i in range(1, self.connection_combo.count()):
                conn = self.connection_combo.itemData(i)
                if isinstance(conn, dict) and conn.get("id") == previous_id:
                    self.connection_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored:
            self.connection_combo.setCurrentIndex(0)
            self.analyze_button.setEnabled(False)
