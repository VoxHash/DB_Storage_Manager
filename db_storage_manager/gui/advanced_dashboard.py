"""
Advanced dashboard with customizable widgets and drag-and-drop
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel,
    QMenu, QAction, QMessageBox, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QPointF
from PyQt6.QtGui import QDrag, QPainter, QColor
from typing import List, Dict, Any, Optional
import json

from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism
from .charts import LineChartWidget, BarChartWidget, PieChartWidget
from .dashboard import DashboardWidget


class DraggableWidget(QWidget):
    """Base draggable widget"""

    def __init__(self, widget_type: str, parent=None):
        super().__init__(parent)
        self.widget_type = widget_type
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        """Handle mouse press for dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(self.widget_type)
            drag.setMimeData(mime_data)
            drag.exec(Qt.DropAction.MoveAction)


class DashboardContainer(QWidget):
    """Container for dashboard widgets with drag-and-drop support"""

    widget_moved = pyqtSignal(str, int, int)  # widget_id, new_x, new_y

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.widgets: Dict[str, QWidget] = {}
        self.layout_positions: Dict[str, Dict[str, int]] = {}

    def dragEnterEvent(self, event):
        """Handle drag enter"""
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle drop"""
        widget_type = event.mimeData().text()
        position = event.position().toPoint()
        self.add_widget(widget_type, position)

    def add_widget(self, widget_type: str, position: Optional[QPointF] = None):
        """Add a widget to the dashboard"""
        widget_id = f"{widget_type}_{len(self.widgets)}"
        
        if widget_type == "chart":
            widget = LineChartWidget("Storage Growth")
        elif widget_type == "table":
            from .dashboard import DashboardWidget
            widget = DashboardWidget([])
        elif widget_type == "summary":
            widget = QLabel("Summary Widget")
        else:
            widget = QLabel(f"{widget_type} Widget")
        
        self.widgets[widget_id] = widget
        if position:
            widget.move(position.x(), position.y())
        else:
            widget.show()
        
        return widget_id

    def remove_widget(self, widget_id: str):
        """Remove a widget"""
        if widget_id in self.widgets:
            self.widgets[widget_id].deleteLater()
            del self.widgets[widget_id]


class AdvancedDashboardWidget(QWidget):
    """Advanced dashboard with customization"""

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
        
        # Widget selector
        toolbar.addWidget(QLabel("Add Widget:"))
        self.widget_combo = QComboBox()
        self.widget_combo.addItems(["Chart", "Table", "Summary", "Metrics"])
        toolbar.addWidget(self.widget_combo)
        
        add_widget_btn = QPushButton("Add Widget")
        add_widget_btn.clicked.connect(self._add_widget)
        toolbar.addWidget(add_widget_btn)
        
        # Filter
        toolbar.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter connections...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_edit)
        
        toolbar.addStretch()
        
        # Real-time update toggle
        self.realtime_check = QCheckBox("Real-time Updates")
        self.realtime_check.setChecked(False)
        toolbar.addWidget(self.realtime_check)
        
        layout.addLayout(toolbar)

        # Dashboard container
        self.container = DashboardContainer()
        layout.addWidget(self.container)

        # Load saved layout
        self._load_layout()

    def _add_widget(self):
        """Add a widget to dashboard"""
        widget_type = self.widget_combo.currentText().lower()
        self.container.add_widget(widget_type)

    def _apply_filter(self, text: str):
        """Apply filter to dashboard"""
        # Filter logic would go here
        pass

    def _load_layout(self):
        """Load saved dashboard layout"""
        # Load from settings
        pass

    def _save_layout(self):
        """Save dashboard layout"""
        # Save to settings
        pass

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections

