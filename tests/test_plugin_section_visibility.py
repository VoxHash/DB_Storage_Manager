"""Plugin UI is hidden until the plugin is enabled, and updates live."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


def _app():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_plugin_ui_state_follows_install_and_enable(marketplace):
    from db_storage_manager.bundled_plugins import bundled_plugin_dir
    from db_storage_manager.plugins.events import plugin_ui_state

    mp, _store, _plugins = marketplace
    plugin_id = "connection-email-alerts"
    assert plugin_ui_state(plugin_id, mp) == "hidden"
    mp.install_from_path(bundled_plugin_dir(plugin_id))
    assert plugin_ui_state(plugin_id, mp) == "shown"
    mp.set_enabled(plugin_id, False)
    assert plugin_ui_state(plugin_id, mp) == "hidden"
    mp.set_enabled(plugin_id, True)
    assert plugin_ui_state(plugin_id, mp) == "shown"


def test_channels_sections_follow_enable_without_restart(
    marketplace, monkeypatch
):
    """The registry signal shows and hides the forms. No showEvent."""
    from db_storage_manager.bundled_plugins import bundled_plugin_dir
    from db_storage_manager.gui.monitoring import MonitoringWidget
    from db_storage_manager.plugins.events import plugin_change_bus
    from db_storage_manager.plugins.licensing import LicenseStatus
    from db_storage_manager.plugins.marketplace import (
        LocalPluginMarketplace,
    )

    mp, _store, _plugins = marketplace
    app = _app()
    widget = MonitoringWidget([])
    try:
        bus = plugin_change_bus()
        assert bus.receivers(bus.changed) >= 1
        assert widget.conn_email_group.isHidden()
        assert widget.multi_group.isHidden()
        assert "not_available" not in widget.conn_email_status.text()
        assert "not_available" not in widget.multi_status.text()

        mp.install_from_path(bundled_plugin_dir("connection-email-alerts"))
        mp.install_from_path(bundled_plugin_dir("multi-connection-monitor"))
        assert widget.conn_email_group.isHidden() is False
        assert widget.conn_email_body.isHidden() is False
        assert widget.multi_group.isHidden() is False
        assert widget.multi_body.isHidden() is False
        assert "not_available" not in widget.conn_email_status.text()
        assert "not_available" not in widget.multi_status.text()

        mp.set_enabled("connection-email-alerts", False)
        mp.set_enabled("multi-connection-monitor", False)
        assert widget.conn_email_group.isHidden()
        assert widget.multi_group.isHidden()

        mp.set_enabled("connection-email-alerts", True)
        mp.set_enabled("multi-connection-monitor", True)
        assert widget.conn_email_body.isHidden() is False
        assert widget.multi_body.isHidden() is False

        real = LocalPluginMarketplace.license_status

        def gated(self, plugin_id, *, network=False):
            if plugin_id in {
                "connection-email-alerts",
                "multi-connection-monitor",
            }:
                return LicenseStatus(
                    plugin_id, "missing", False, "License required"
                )
            return real(self, plugin_id, network=network)

        monkeypatch.setattr(LocalPluginMarketplace, "license_status", gated)
        mp.set_enabled("connection-email-alerts", True)
        mp.set_enabled("multi-connection-monitor", True)
        assert widget.conn_email_group.isHidden() is False
        assert widget.conn_email_body.isHidden()
        assert widget.multi_group.isHidden() is False
        assert widget.multi_body.isHidden()
        assert widget.conn_email_status.text().startswith("not_available")
        assert widget.multi_status.text().startswith("not_available")
    finally:
        widget.shutdown()
        widget.close()
        app.processEvents()


def test_discover_cloud_omits_a_disabled_plugin(marketplace, monkeypatch):
    from db_storage_manager.gui.connections import CloudDiscoverDialog
    from db_storage_manager.plugins import events as events_mod

    app = _app()
    dialog = CloudDiscoverDialog()
    try:
        assert dialog.premium_note.isHidden()
        calls = []

        def fail_load(*_args, **_kwargs):
            calls.append("load")
            raise AssertionError("plugin was imported")

        monkeypatch.setattr(
            "db_storage_manager.plugins.loader.load_plugin_from_directory",
            fail_load,
        )
        rows, note = dialog._premium_discovery()
        assert rows == []
        assert note == ""
        assert calls == []

        def gated(plugin_id, marketplace=None):
            if plugin_id == "multi-cloud-discovery":
                return "gated"
            return "hidden"

        monkeypatch.setattr(events_mod, "plugin_ui_state", gated)
        monkeypatch.setattr(
            events_mod,
            "plugin_gate_reason",
            lambda plugin_id, marketplace=None: (
                "not_available: License required"
            ),
        )
        dialog._on_plugin_registry_changed("multi-cloud-discovery", True)
        assert dialog.premium_note.isHidden() is False
        assert dialog.premium_note.text().startswith("not_available")
        rows, note = dialog._premium_discovery()
        assert rows == []
        assert note == ""
        assert calls == []
    finally:
        dialog.close()
        app.processEvents()


def test_run_dialog_hides_fields_when_the_plugin_is_disabled(
    marketplace, monkeypatch
):
    from db_storage_manager.gui.plugin_run import PluginRunDialog
    from db_storage_manager.plugins.licensing import LicenseStatus
    from db_storage_manager.plugins.marketplace import (
        LocalPluginMarketplace,
    )

    mp, _store, _plugins = marketplace
    mp.sync_builtins()
    app = _app()
    dialog = PluginRunDialog("migration", [], mp)
    try:
        assert dialog._fields.isHidden() is False
        assert dialog.run_btn.isHidden() is False
        assert dialog._gate.isHidden()
        mp.set_enabled("migration", False)
        assert dialog._fields.isHidden()
        assert dialog.run_btn.isHidden()
        assert dialog._gate.isHidden()
        mp.set_enabled("migration", True)
        assert dialog._fields.isHidden() is False
        assert dialog.run_btn.isHidden() is False

        real = LocalPluginMarketplace.license_status

        def gated(self, plugin_id, *, network=False):
            if plugin_id == "migration":
                return LicenseStatus(
                    plugin_id, "missing", False, "License required"
                )
            return real(self, plugin_id, network=network)

        monkeypatch.setattr(LocalPluginMarketplace, "license_status", gated)
        mp.set_enabled("migration", True)
        assert dialog._fields.isHidden()
        assert dialog.run_btn.isHidden()
        assert dialog._gate.isHidden() is False
        assert dialog._gate.text().startswith("not_available")
    finally:
        dialog.close()
        app.processEvents()
