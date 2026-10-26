"""Offscreen smoke for per-tab content polish (metric cards, dense lists, page chrome)."""

from __future__ import annotations

import os

import pytest

from db_storage_manager.config import DASHBOARD_METRIC_KEYS
from db_storage_manager.gui.utils import (
    DENSE_ROW_HEIGHT,
    PAGE_MARGINS,
    build_app_stylesheet,
    configure_dense_table,
    make_metric_card,
    make_page_header,
)
from db_storage_manager.themes.themes import THEMES


def test_stylesheet_includes_page_and_metric_tokens():
    for theme_key, theme in THEMES.items():
        sheet = build_app_stylesheet(theme["colors"])
        assert "PageTitle" in sheet, theme_key
        assert "MetricCard" in sheet, theme_key
        assert "DenseTable" in sheet, theme_key
        assert theme["colors"]["primary"] in sheet


def test_make_page_header_and_metric_card_offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget

    app = QApplication.instance() or QApplication([])

    header = make_page_header("Dashboard", "Storage analysis")
    title = header.findChild(QLabel, "PageTitle")
    subtitle = header.findChild(QLabel, "PageSubtitle")
    assert title is not None and title.text() == "Dashboard"
    assert subtitle is not None and "Storage" in subtitle.text()

    card, value = make_metric_card("Total size", "—", object_name="dashboardMetric_total_size")
    assert card.objectName() == "MetricCard"
    assert value.objectName() == "dashboardMetric_total_size"
    assert value.text() == "—"
    value.setText("12.00 MB")
    assert value.text() == "12.00 MB"

    table = QTableWidget(3, 2)
    configure_dense_table(table)
    assert table.objectName() == "DenseTable"
    assert table.alternatingRowColors()
    assert not table.showGrid()
    assert not table.verticalHeader().isVisible()
    assert table.verticalHeader().defaultSectionSize() == DENSE_ROW_HEIGHT
    assert PAGE_MARGINS == (20, 16, 20, 16)

    del app


def test_dashboard_and_connections_polish_offscreen(isolated_secure_store, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    store, data_dir = isolated_secure_store

    import db_storage_manager.themes.manager as theme_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QFrame, QLabel

    app = QApplication.instance() or QApplication([])

    from db_storage_manager.gui.connections import ConnectionsWidget
    from db_storage_manager.gui.dashboard import DashboardWidget
    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.themes.manager import get_theme_manager

    get_theme_manager().set_theme("dark")

    connections = [
        {
            "id": "c1",
            "name": "Local SQLite",
            "type": "sqlite",
            "host": "",
            "port": 0,
            "database": ":memory:",
            "username": "",
            "password": "",
        },
        {
            "id": "c2",
            "name": "Demo PG",
            "type": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "database": "demo",
            "username": "demo",
            "password": "",
        },
    ]
    store.save_connections(connections)

    dash = DashboardWidget(connections)
    for key in DASHBOARD_METRIC_KEYS:
        card = dash._metric_cards[key]
        assert isinstance(card, QFrame)
        assert card.objectName() == "MetricCard"
        value = dash._metric_labels[key]
        assert value.objectName() == f"dashboardMetric_{key}"
    assert dash.findChild(QLabel, "PageTitle") is not None
    assert dash.tables_table.objectName() == "DenseTable"
    assert dash.analyze_button.objectName() == "PrimaryButton"

    dash._update_display(
        {"totalSize": 1536, "tableCount": 4, "indexCount": 2, "tables": []}
    )
    assert "KB" in dash._metric_labels["total_size"].text() or "B" in dash._metric_labels[
        "total_size"
    ].text()
    assert dash._metric_labels["tables"].text() == "4"
    assert dash._metric_labels["indexes"].text() == "2"

    # Hide one watched metric → card + value visibility follow layout prefs
    dash._metric_checks["indexes"].setChecked(False)
    assert dash._metric_cards["indexes"].isHidden()
    assert dash._metric_labels["indexes"].isHidden()

    conn_widget = ConnectionsWidget(connections)
    assert conn_widget.table.objectName() == "DenseTable"
    assert conn_widget.table.rowCount() == 2
    assert conn_widget.add_button.objectName() == "PrimaryButton"
    assert conn_widget.count_label is not None
    assert "2" in conn_widget.count_label.text()

    window = MainWindow()
    window.show()
    app.processEvents()

    # All seven sections expose page titles after polish
    for index in range(window.tab_widget.count()):
        window.tab_widget.setCurrentIndex(index)
        app.processEvents()
        page = window.tab_widget.widget(index)
        title = page.findChild(QLabel, "PageTitle")
        assert title is not None, f"missing PageTitle on tab {index}"

    # Dense connection list still reachable via nav
    window.sidebar._buttons[1].click()
    app.processEvents()
    assert window.connections_widget.table.objectName() == "DenseTable"
    assert window.dashboard._metric_cards["total_size"].objectName() == "MetricCard"

    window.close()
    dash.close()
    conn_widget.close()
