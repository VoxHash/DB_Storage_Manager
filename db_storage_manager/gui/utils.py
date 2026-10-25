"""
GUI utilities for styling and i18n
"""

from __future__ import annotations

from typing import Any, Mapping

from PyQt6.QtWidgets import QWidget

from ..themes.manager import get_theme_manager


def _c(colors: Mapping[str, str], key: str, fallback: str) -> str:
    return colors.get(key) or fallback


def build_app_stylesheet(colors: Mapping[str, str]) -> str:
    """Build the desktop-shell stylesheet from theme color tokens."""
    bg = _c(colors, "background", "#0B0F14")
    surface = _c(colors, "surface", "#121820")
    elevated = _c(colors, "surface_elevated", surface)
    primary = _c(colors, "primary", "#2DD4BF")
    primary_hover = _c(colors, "primary_hover", primary)
    secondary = _c(colors, "secondary", "#94A3B8")
    text = _c(colors, "text", "#E8EEF4")
    muted = _c(colors, "text_secondary", "#94A3B8")
    border = _c(colors, "border", "#243044")
    sidebar_bg = _c(colors, "sidebar_bg", bg)
    sidebar_hover = _c(colors, "sidebar_hover", elevated)
    sidebar_active = _c(colors, "sidebar_active", elevated)
    content_bg = _c(colors, "content_bg", bg)
    row_alt = _c(colors, "row_alt", surface)
    input_bg = _c(colors, "input_bg", elevated)
    selection = _c(colors, "selection", "#1E3A4A")
    on_primary = _c(colors, "on_primary", "#042F2E")
    success = _c(colors, "success", "#34D399")
    error = _c(colors, "error", "#F87171")
    warning = _c(colors, "warning", "#FBBF24")

    return f"""
        QMainWindow, QDialog {{
            background-color: {bg};
            color: {text};
        }}
        QWidget {{
            color: {text};
            font-size: 13px;
        }}
        QToolTip {{
            background-color: {elevated};
            color: {text};
            border: 1px solid {border};
            padding: 6px 8px;
        }}
        QMenuBar {{
            background-color: {surface};
            color: {text};
            border-bottom: 1px solid {border};
            padding: 2px 4px;
        }}
        QMenuBar::item {{
            padding: 6px 10px;
            border-radius: 4px;
        }}
        QMenuBar::item:selected {{
            background-color: {sidebar_hover};
            color: {primary};
        }}
        QMenu {{
            background-color: {elevated};
            color: {text};
            border: 1px solid {border};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 8px 24px 8px 12px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {selection};
            color: {primary};
        }}
        QStatusBar {{
            background-color: {surface};
            color: {muted};
            border-top: 1px solid {border};
            min-height: 22px;
        }}
        QStatusBar::item {{
            border: none;
        }}
        #ContentShell {{
            background-color: {content_bg};
        }}
        #NavSidebar {{
            background-color: {sidebar_bg};
            border-right: 1px solid {border};
        }}
        #NavBrand {{
            color: {text};
            font-size: 15px;
            font-weight: 700;
            letter-spacing: -0.4px;
            background: transparent;
            padding: 0 4px;
        }}
        #NavCaption {{
            color: {muted};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.6px;
            text-transform: uppercase;
            background: transparent;
            padding: 0 4px 8px 4px;
        }}
        #NavSection {{
            color: {muted};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.4px;
            background: transparent;
            padding: 4px 8px 6px 8px;
        }}
        #NavFooter {{
            color: {muted};
            font-size: 11px;
            background: transparent;
            padding: 8px 4px 0 4px;
        }}
        #NavSidebar QPushButton#NavItem {{
            background-color: transparent;
            color: {muted};
            border: none;
            border-left: 2px solid transparent;
            border-radius: 6px;
            text-align: left;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: 500;
        }}
        #NavSidebar QPushButton#NavItem:hover {{
            background-color: {sidebar_hover};
            color: {text};
        }}
        #NavSidebar QPushButton#NavItem:checked {{
            background-color: {sidebar_active};
            color: {primary};
            border-left: 2px solid {primary};
            font-weight: 600;
        }}
        #NavSidebar QPushButton#NavItem:focus {{
            outline: none;
        }}
        #NavSidebar QPushButton#NavItem:focus-visible {{
            border: 1px solid {primary};
        }}
        QTabWidget::pane {{
            border: none;
            background-color: {content_bg};
        }}
        QTabBar::tab {{
            background-color: {surface};
            color: {muted};
            padding: 8px 16px;
            border: 1px solid {border};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background-color: {content_bg};
            color: {primary};
            border-bottom: 2px solid {primary};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {sidebar_hover};
            color: {text};
        }}
        QPushButton {{
            background-color: {elevated};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 8px 14px;
            min-height: 20px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {sidebar_hover};
            border-color: {primary};
            color: {text};
        }}
        QPushButton:pressed {{
            background-color: {selection};
        }}
        QPushButton:disabled {{
            background-color: {surface};
            color: {muted};
            border-color: {border};
        }}
        QPushButton#PrimaryButton, QPushButton[cssClass="primary"] {{
            background-color: {primary};
            color: {on_primary};
            border: 1px solid {primary};
        }}
        QPushButton#PrimaryButton:hover, QPushButton[cssClass="primary"]:hover {{
            background-color: {primary_hover};
            border-color: {primary_hover};
            color: {on_primary};
        }}
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {input_bg};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 7px 10px;
            selection-background-color: {selection};
            selection-color: {text};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
            border: 1px solid {primary};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {elevated};
            color: {text};
            border: 1px solid {border};
            selection-background-color: {selection};
            outline: none;
        }}
        QTableWidget, QTableView, QTreeWidget, QListWidget {{
            background-color: {surface};
            alternate-background-color: {row_alt};
            color: {text};
            border: 1px solid {border};
            border-radius: 8px;
            gridline-color: {border};
            outline: none;
        }}
        QTableWidget::item, QTableView::item, QTreeWidget::item, QListWidget::item {{
            padding: 6px 8px;
        }}
        QTableWidget::item:selected, QTableView::item:selected,
        QTreeWidget::item:selected, QListWidget::item:selected {{
            background-color: {selection};
            color: {text};
        }}
        QHeaderView::section {{
            background-color: {elevated};
            color: {muted};
            padding: 8px 10px;
            border: none;
            border-right: 1px solid {border};
            border-bottom: 1px solid {border};
            font-weight: 600;
            font-size: 12px;
        }}
        QGroupBox {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: {text};
        }}
        QCheckBox, QRadioButton {{
            color: {text};
            spacing: 8px;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {border};
            background-color: {input_bg};
        }}
        QCheckBox::indicator {{
            border-radius: 4px;
        }}
        QRadioButton::indicator {{
            border-radius: 9px;
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {primary};
            border-color: {primary};
        }}
        QScrollBar:vertical {{
            background: {bg};
            width: 10px;
            margin: 0;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {border};
            border-radius: 5px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {secondary};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            height: 0;
            background: none;
        }}
        QScrollBar:horizontal {{
            background: {bg};
            height: 10px;
            margin: 0;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {border};
            border-radius: 5px;
            min-width: 28px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {secondary};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            width: 0;
            background: none;
        }}
        QProgressBar {{
            background-color: {input_bg};
            border: 1px solid {border};
            border-radius: 6px;
            text-align: center;
            color: {text};
            min-height: 16px;
        }}
        QProgressBar::chunk {{
            background-color: {primary};
            border-radius: 5px;
        }}
        QSplitter::handle {{
            background-color: {border};
        }}
        QLabel#StatusSuccess {{ color: {success}; }}
        QLabel#StatusError {{ color: {error}; }}
        QLabel#StatusWarning {{ color: {warning}; }}
        #LoginCard {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: 12px;
        }}
        #LoginTitle {{
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.3px;
            color: {text};
            background: transparent;
        }}
        #LoginHint {{
            color: {muted};
            background: transparent;
        }}
    """


def apply_glassmorphism(widget: QWidget) -> None:
    """Apply elevated surface styling to a panel widget."""
    theme_manager = get_theme_manager()
    theme = theme_manager.get_theme()
    glass = theme["glassmorphism"]
    colors = theme["colors"]
    primary = _c(colors, "primary", "#2DD4BF")
    primary_hover = _c(colors, "primary_hover", primary)
    on_primary = _c(colors, "on_primary", "#042F2E")
    text = _c(colors, "text", "#E8EEF4")
    muted = _c(colors, "text_secondary", "#94A3B8")
    surface = _c(colors, "surface", "#121820")
    border = _c(colors, "border", "#243044")
    input_bg = _c(colors, "input_bg", surface)

    widget.setStyleSheet(
        f"""
        QWidget {{
            background-color: {glass['background']};
            border: 1px solid {glass['border']};
            border-radius: 10px;
        }}
        QLabel {{
            color: {text};
            background: transparent;
            border: none;
        }}
        QPushButton {{
            background-color: {primary};
            color: {on_primary};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {primary_hover};
        }}
        QPushButton:disabled {{
            background-color: {border};
            color: {muted};
        }}
        QComboBox, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
            background-color: {input_bg};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 8px;
        }}
        QTableWidget {{
            background-color: {surface};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            gridline-color: {border};
            alternate-background-color: {_c(colors, 'row_alt', surface)};
        }}
        QTableWidget::item {{
            padding: 4px;
        }}
        QHeaderView::section {{
            background-color: {_c(colors, 'surface_elevated', surface)};
            color: {muted};
            padding: 6px;
            border: none;
            border-bottom: 1px solid {border};
            font-weight: 600;
        }}
        QCheckBox {{
            color: {text};
            background: transparent;
            border: none;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {border};
            border-radius: 4px;
            background-color: {input_bg};
        }}
        QCheckBox::indicator:checked {{
            background-color: {primary};
            border-color: {primary};
        }}
        QGroupBox {{
            color: {text};
            border: 1px solid {border};
            border-radius: 8px;
            margin-top: 10px;
            background-color: {surface};
        }}
    """
    )


def apply_theme_to_app(app: Any) -> None:
    """Apply the current theme stylesheet to a QApplication or top-level widget."""
    theme_manager = get_theme_manager()
    theme = theme_manager.get_theme()
    colors = theme["colors"]
    app.setStyleSheet(build_app_stylesheet(colors))


__all__ = [
    "apply_glassmorphism",
    "apply_theme_to_app",
    "build_app_stylesheet",
]
