"""
Chart visualization components using PyQt6-Charts
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QBarSeries, QBarSet, QPieSeries, QValueAxis, QBarCategoryAxis
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor
from typing import List, Dict, Any, Optional


class ChartWidget(QWidget):
    """Base chart widget with export capabilities"""

    def __init__(self, title: str = ""):
        super().__init__()
        self.chart = QChart()
        self.chart.setTitle(title)
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        toolbar = QHBoxLayout()
        self.export_png_btn = QPushButton("Export PNG")
        self.export_png_btn.clicked.connect(self.export_png)
        self.export_pdf_btn = QPushButton("Export PDF")
        self.export_pdf_btn.clicked.connect(self.export_pdf)
        toolbar.addWidget(self.export_png_btn)
        toolbar.addWidget(self.export_pdf_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        layout.addWidget(self.chart_view)

    def export_png(self, filename: Optional[str] = None):
        """Export chart to PNG"""
        from PyQt6.QtGui import QPixmap
        pixmap = self.chart_view.grab()
        if filename:
            pixmap.save(filename, "PNG")
        else:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(self, "Save PNG", "", "PNG Files (*.png)")
            if filename:
                pixmap.save(filename, "PNG")

    def export_pdf(self, filename: Optional[str] = None):
        """Export chart to PDF"""
        from PyQt6.QtPrintSupport import QPrinter
        from PyQt6.QtGui import QPainter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        if filename:
            printer.setOutputFileName(filename)
        else:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(self, "Save PDF", "", "PDF Files (*.pdf)")
            if filename:
                printer.setOutputFileName(filename)
            else:
                return
        
        painter = QPainter(printer)
        self.chart_view.render(painter)
        painter.end()


class LineChartWidget(ChartWidget):
    """Line chart widget"""

    def __init__(self, title: str = "", x_label: str = "", y_label: str = ""):
        super().__init__(title)
        self.x_label = x_label
        self.y_label = y_label
        self.series_list = []

    def add_series(self, name: str, data: List[QPointF]):
        """Add a data series"""
        series = QLineSeries()
        series.setName(name)
        for point in data:
            series.append(point)
        self.chart.addSeries(series)
        self.series_list.append(series)
        
        # Create axes
        axis_x = QValueAxis()
        axis_x.setTitleText(self.x_label)
        axis_y = QValueAxis()
        axis_y.setTitleText(self.y_label)
        self.chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        
        for series in self.series_list:
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
        
        self.chart.createDefaultAxes()


class BarChartWidget(ChartWidget):
    """Bar chart widget"""

    def __init__(self, title: str = "", categories: List[str] = None):
        super().__init__(title)
        self.categories = categories or []
        self.bar_series = QBarSeries()

    def add_data_set(self, name: str, values: List[float]):
        """Add a data set"""
        bar_set = QBarSet(name)
        for value in values:
            bar_set.append(value)
        self.bar_series.append(bar_set)
        self.chart.addSeries(self.bar_series)
        
        # Create axes
        axis_x = QBarCategoryAxis()
        axis_x.append(self.categories)
        axis_y = QValueAxis()
        self.chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        self.bar_series.attachAxis(axis_x)
        self.bar_series.attachAxis(axis_y)


class PieChartWidget(ChartWidget):
    """Pie chart widget"""

    def __init__(self, title: str = ""):
        super().__init__(title)
        self.pie_series = QPieSeries()
        self.chart.addSeries(self.pie_series)

    def add_slice(self, label: str, value: float):
        """Add a slice to the pie chart"""
        self.pie_series.append(label, value)

