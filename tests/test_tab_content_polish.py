"""Offscreen smoke for per-tab content polish (metric cards, dense lists, page chrome)."""

from __future__ import annotations

import os
from pathlib import Path

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

_THEME_KEYS = ("dark", "light", "dracula")  # Atmospheric / Light / Dracula
_NAV_SECTION_COUNT = 7
_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "theme_visual"
# WCAG AA normal-text floor; UI chrome pairs use the large-text floor (3.0).
_CONTRAST_AA = 4.5
_CONTRAST_UI = 3.0


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    raw = value.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _relative_luminance(hex_color: str) -> float:
    channels = []
    for channel in _hex_to_rgb(hex_color):
        if channel <= 0.03928:
            channels.append(channel / 12.92)
        else:
            channels.append(((channel + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg: str, bg: str) -> float:
    lighter = max(_relative_luminance(fg), _relative_luminance(bg))
    darker = min(_relative_luminance(fg), _relative_luminance(bg))
    return (lighter + 0.05) / (darker + 0.05)


def test_stylesheet_includes_page_and_metric_tokens():
    for theme_key, theme in THEMES.items():
        sheet = build_app_stylesheet(theme["colors"])
        assert "PageTitle" in sheet, theme_key
        assert "MetricCard" in sheet, theme_key
        assert "DenseTable" in sheet, theme_key
        assert theme["colors"]["primary"] in sheet


def test_theme_token_contrast_readable():
    """Lock readable ink/surface contrast for Atmospheric / Light / Dracula."""
    for theme_key in _THEME_KEYS:
        colors = THEMES[theme_key]["colors"]
        pairs = (
            (colors["text"], colors["background"], _CONTRAST_AA, "text/background"),
            (colors["text"], colors["surface"], _CONTRAST_AA, "text/surface"),
            (colors["text"], colors["content_bg"], _CONTRAST_AA, "text/content_bg"),
            (
                colors["text_secondary"],
                colors["surface"],
                _CONTRAST_UI,
                "muted/surface",
            ),
            (
                colors["on_primary"],
                colors["primary"],
                _CONTRAST_UI,
                "on_primary/primary",
            ),
            (
                colors["text"],
                colors["surface_elevated"],
                _CONTRAST_AA,
                "text/elevated",
            ),
        )
        for fg, bg, minimum, label in pairs:
            ratio = _contrast_ratio(fg, bg)
            assert ratio >= minimum, (
                f"{theme_key} {label}: {ratio:.2f} < {minimum} ({fg} on {bg})"
            )


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


def test_live_theme_visual_pass_offscreen(isolated_secure_store, monkeypatch):
    """Atmospheric / Light / Dracula × seven polished tabs: chrome + grab assertions."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    store, data_dir = isolated_secure_store

    import db_storage_manager.themes.manager as theme_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget, QWidget

    app = QApplication.instance() or QApplication([])

    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.themes.manager import get_theme_manager

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

    get_theme_manager().set_theme("dark")
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()

    assert window.tab_widget.count() == _NAV_SECTION_COUNT
    assert window.plugins_widget.objectName() == "glassmorphism"

    grab_dir = Path(os.environ.get("DSM_THEME_ARTIFACT_DIR", str(_ARTIFACT_DIR)))
    grab_dir.mkdir(parents=True, exist_ok=True)

    evidence: list[str] = []
    for theme_key in _THEME_KEYS:
        colors = THEMES[theme_key]["colors"]
        get_theme_manager().set_theme(theme_key)
        window._on_theme_changed(theme_key)
        app.processEvents()

        # Shell + glass panels must both carry the active theme (no stale Atmospheric).
        assert colors["primary"] in window.styleSheet(), theme_key
        assert colors["surface_elevated"] in window.dashboard.styleSheet(), theme_key
        assert colors["primary"] in window.dashboard.styleSheet(), theme_key
        assert "MetricCard" in window.dashboard.styleSheet(), theme_key
        # Single glass root — avoid nested #glassmorphism double-box on polished tabs.
        for panel in (
            window.dashboard,
            window.connections_widget,
            window.query_widget,
            window.backups_widget,
            window.monitoring_widget,
            window.plugins_widget,
            window.settings_widget,
        ):
            assert panel.objectName() == "glassmorphism", panel.__class__.__name__
            nested = [
                child
                for child in panel.findChildren(QWidget, "glassmorphism")
                if child is not panel
            ]
            assert not nested, f"{theme_key} nested glass on {panel.__class__.__name__}"

        for index in range(_NAV_SECTION_COUNT):
            window.sidebar._buttons[index].click()
            app.processEvents()
            page = window.tab_widget.widget(index)
            assert page is not None and page.isVisible()
            title = page.findChild(QLabel, "PageTitle")
            assert title is not None and title.text().strip(), (
                f"{theme_key} tab {index} missing PageTitle"
            )
            assert title.isVisible()

            grab = page.grab()
            assert not grab.isNull(), f"{theme_key} tab {index} null grab"
            assert grab.width() >= 400 and grab.height() >= 200, (
                f"{theme_key} tab {index} grab too small: "
                f"{grab.width()}x{grab.height()}"
            )
            out = grab_dir / f"offscreen_{theme_key}_tab{index}.png"
            assert grab.save(str(out)), f"failed to write {out}"
            evidence.append(f"{theme_key}/tab{index}")

        # Dashboard cards + dense connection inventory under each theme
        window.sidebar._buttons[0].click()
        app.processEvents()
        for key in DASHBOARD_METRIC_KEYS:
            card = window.dashboard._metric_cards[key]
            assert card.objectName() == "MetricCard"
            assert card.isVisible() or window.dashboard._metric_labels[key].isHidden()
        window.sidebar._buttons[1].click()
        app.processEvents()
        assert window.connections_widget.table.objectName() == "DenseTable"
        assert window.connections_widget.table.rowCount() >= 2
        dense = window.connections_widget.findChildren(QTableWidget, "DenseTable")
        assert dense

    assert len(evidence) == len(_THEME_KEYS) * _NAV_SECTION_COUNT
    window.close()
