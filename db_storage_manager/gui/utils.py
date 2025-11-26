"""
GUI utilities for styling and i18n
"""

from PyQt6.QtWidgets import QWidget
from ..i18n.manager import get_i18n_manager
from ..themes.manager import get_theme_manager


def apply_glassmorphism(widget: QWidget) -> None:
    """Apply glassmorphism styling to a widget"""
    theme_manager = get_theme_manager()
    theme = theme_manager.get_theme()
    glass = theme["glassmorphism"]
    colors = theme["colors"]

    # Apply glassmorphism background to the widget itself
    widget.setStyleSheet(
        f"""
        QWidget {{
            background-color: {glass['background']};
            border: 1px solid {glass['border']};
            border-radius: 12px;
            padding: 10px;
        }}
        QLabel {{
            color: {colors['text']};
            background: transparent;
        }}
        QPushButton {{
            background-color: {colors['primary']};
            color: {colors['text']};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {colors['secondary']};
        }}
        QPushButton:disabled {{
            background-color: {colors['border']};
            color: {colors['text_secondary']};
        }}
        QComboBox {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
            border-radius: 6px;
            padding: 6px;
        }}
        QLineEdit, QTextEdit {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
            border-radius: 6px;
            padding: 6px;
        }}
        QTableWidget {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
            border-radius: 6px;
            gridline-color: {colors['border']};
        }}
        QTableWidget::item {{
            padding: 4px;
        }}
        QHeaderView::section {{
            background-color: {colors['primary']};
            color: {colors['text']};
            padding: 6px;
            border: none;
        }}
        QCheckBox {{
            color: {colors['text']};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {colors['border']};
            border-radius: 4px;
            background-color: {colors['surface']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors['primary']};
        }}
        QSpinBox {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
            border-radius: 6px;
            padding: 6px;
        }}
    """
    )


def apply_theme_to_app(app) -> None:
    """Apply theme to entire application"""
    theme_manager = get_theme_manager()
    theme = theme_manager.get_theme()
    colors = theme["colors"]

    app.setStyleSheet(
        f"""
        QMainWindow {{
            background-color: {colors['background']};
            color: {colors['text']};
        }}
        QWidget {{
            background-color: {colors['background']};
            color: {colors['text']};
        }}
        QMenuBar {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border-bottom: 1px solid {colors['border']};
        }}
        QMenuBar::item {{
            padding: 4px 8px;
        }}
        QMenuBar::item:selected {{
            background-color: {colors['primary']};
        }}
        QMenu {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
        }}
        QMenu::item:selected {{
            background-color: {colors['primary']};
        }}
        QStatusBar {{
            background-color: {colors['surface']};
            color: {colors['text']};
            border-top: 1px solid {colors['border']};
        }}
        QTabWidget {{
            background-color: {colors['background']};
        }}
        QTabWidget::pane {{
            border: 1px solid {colors['border']};
            background-color: {colors['background']};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {colors['surface']};
            color: {colors['text']};
            padding: 8px 16px;
            border: 1px solid {colors['border']};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background-color: {colors['background']};
            color: {colors['text']};
            border-bottom: 2px solid {colors['primary']};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {colors['secondary']};
        }}
    """
    )
