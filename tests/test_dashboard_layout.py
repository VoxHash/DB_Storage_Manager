"""Dashboard layout / watched-metrics prefs and offscreen Qt smoke."""

from __future__ import annotations

import copy
import os

import pytest

from db_storage_manager.config import (
    DASHBOARD_COLUMN_KEYS,
    DASHBOARD_METRIC_KEYS,
    DEFAULT_DASHBOARD_LAYOUT,
)
from db_storage_manager.dashboard_prefs import (
    apply_named_layout,
    delete_named_layout,
    normalize_dashboard_layout,
    save_named_layout,
    snapshot_from_layout,
)


def test_normalize_dashboard_layout_defaults():
    layout = normalize_dashboard_layout(None)
    assert layout["watched_metrics"] == list(DASHBOARD_METRIC_KEYS)
    assert layout["table_columns"] == list(DASHBOARD_COLUMN_KEYS)
    assert layout["active_layout"] == "Default"
    assert "Default" in layout["saved_layouts"]


def test_normalize_filters_unknown_and_keeps_order():
    raw = {
        "watched_metrics": ["indexes", "bogus", "total_size", "indexes"],
        "table_columns": ["bloat", "name", "nope"],
        "metric_order": ["tables", "indexes", "total_size"],
        "saved_layouts": {"Compact": {"watched_metrics": ["total_size"], "table_columns": ["name"]}},
        "active_layout": "Compact",
        "last_connection_id": "conn-1",
    }
    layout = normalize_dashboard_layout(raw)
    assert layout["watched_metrics"] == ["indexes", "total_size"]
    assert layout["table_columns"] == ["bloat", "name"]
    assert layout["metric_order"] == ["indexes", "total_size"]
    assert layout["active_layout"] == "Compact"
    assert layout["last_connection_id"] == "conn-1"
    assert layout["saved_layouts"]["Compact"]["watched_metrics"] == ["total_size"]
    assert "Default" in layout["saved_layouts"]


def test_save_apply_delete_named_layouts():
    layout = normalize_dashboard_layout(None)
    layout["watched_metrics"] = ["total_size"]
    layout["table_columns"] = ["name", "size"]
    layout["metric_order"] = ["total_size"]
    layout = save_named_layout(layout, "Size only")
    assert layout["active_layout"] == "Size only"
    assert layout["saved_layouts"]["Size only"]["watched_metrics"] == ["total_size"]

    layout["watched_metrics"] = list(DASHBOARD_METRIC_KEYS)
    layout = apply_named_layout(layout, "Size only")
    assert layout["watched_metrics"] == ["total_size"]
    assert layout["table_columns"] == ["name", "size"]

    layout = delete_named_layout(layout, "Size only")
    assert "Size only" not in layout["saved_layouts"]
    assert layout["active_layout"] == "Default"
    assert layout["watched_metrics"] == list(DASHBOARD_METRIC_KEYS)

    with pytest.raises(ValueError):
        delete_named_layout(layout, "Default")


def test_dashboard_layout_persists_via_secure_store(isolated_secure_store):
    store, _ = isolated_secure_store
    settings = store.get_settings()
    assert "dashboard_layout" in settings
    assert settings["dashboard_layout"]["active_layout"] == "Default"

    layout = copy.deepcopy(DEFAULT_DASHBOARD_LAYOUT)
    layout["watched_metrics"] = ["tables", "indexes"]
    layout["table_columns"] = ["name", "rows"]
    layout["metric_order"] = ["tables", "indexes"]
    layout["last_connection_id"] = "abc-123"
    layout = save_named_layout(layout, "Ops glance")
    settings["dashboard_layout"] = layout
    store.set_settings(settings)

    reloaded = store.get_settings()["dashboard_layout"]
    assert reloaded["watched_metrics"] == ["tables", "indexes"]
    assert reloaded["table_columns"] == ["name", "rows"]
    assert reloaded["last_connection_id"] == "abc-123"
    assert reloaded["active_layout"] == "Ops glance"
    assert "Ops glance" in reloaded["saved_layouts"]
    assert snapshot_from_layout(reloaded)["watched_metrics"] == ["tables", "indexes"]


def test_dashboard_widget_offscreen_smoke(isolated_secure_store, monkeypatch):
    _store, _ = isolated_secure_store
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from db_storage_manager.gui.dashboard import DashboardWidget

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )

    app = QApplication.instance() or QApplication([])
    connections = [
        {
            "id": "dash-1",
            "name": "Demo SQLite",
            "type": "sqlite",
            "database": ":memory:",
        }
    ]
    widget = DashboardWidget(connections)
    assert widget.analyze_button.isEnabled() is False
    assert "total_size" in widget._metric_checks
    assert "name" in widget._column_checks
    assert widget.layout_combo.findText("Default") >= 0

    # Hide indexes metric + bloat column; persists through SecureStore
    widget._metric_checks["indexes"].setChecked(False)
    widget._column_checks["bloat"].setChecked(False)
    saved = widget.secure_store.get_settings()["dashboard_layout"]
    assert "indexes" not in saved["watched_metrics"]
    assert "bloat" not in saved["table_columns"]
    assert widget._metric_labels["indexes"].isVisible() is False
    assert widget.tables_table.isColumnHidden(
        list(DASHBOARD_COLUMN_KEYS).index("bloat")
    )

    # Save as named layout and reload via a new widget instance
    widget.layout_prefs = save_named_layout(widget.layout_prefs, "No bloat")
    widget._persist_layout_prefs()

    widget.connection_combo.setCurrentIndex(1)
    assert widget.analyze_button.isEnabled() is True
    assert (
        widget.secure_store.get_settings()["dashboard_layout"]["last_connection_id"]
        == "dash-1"
    )

    widget2 = DashboardWidget(connections)
    reloaded = widget2.layout_prefs
    assert "indexes" not in reloaded["watched_metrics"]
    assert "bloat" not in reloaded["table_columns"]
    assert "No bloat" in reloaded["saved_layouts"]
    assert widget2.connection_combo.currentIndex() == 1
    assert widget2._metric_labels["indexes"].isVisible() is False

    widget2.layout_combo.setCurrentText("No bloat")
    widget2._apply_selected_layout()
    assert widget2.layout_prefs["active_layout"] == "No bloat"

    widget.close()
    widget2.close()
    app.processEvents()
