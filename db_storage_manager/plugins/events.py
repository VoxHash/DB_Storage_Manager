"""Tell open windows when the plugin registry changes.

``LocalPluginMarketplace`` calls ``notify_plugin_changed`` after enable,
disable, install, uninstall, and licence changes. Widgets connect to
``plugin_change_bus().changed`` and show or hide plugin sections on that
Qt signal. No restart is required.

The bus is created the first time a window asks for it, so enable/disable
in a process with no GUI does not construct a ``QObject``.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal


class PluginChangeBus(QObject):
    """Process-wide signal for plugin enable, disable, and licence changes.

    ``changed`` carries the plugin id and the Enabled flag that was just
    stored. Listeners re-read install and licence state; the flag alone does
    not decide whether a form is shown.
    """

    changed = pyqtSignal(str, bool)


_bus: Optional[PluginChangeBus] = None


def _living_bus() -> Optional[PluginChangeBus]:
    """Return the bus, or ``None`` when Qt has already deleted it.

    Destroying ``QApplication`` deletes every ``QObject``, including this bus.
    The next window creates a new one.
    """
    global _bus
    if _bus is None:
        return None
    try:
        _bus.signalsBlocked()
    except RuntimeError:
        _bus = None
        return None
    return _bus


def plugin_change_bus() -> PluginChangeBus:
    """Return the shared bus, creating it on the thread that first asks."""
    global _bus
    bus = _living_bus()
    if bus is None:
        _bus = PluginChangeBus()
        return _bus
    return bus


def notify_plugin_changed(plugin_id: str, enabled: bool) -> None:
    """Emit when a window is already listening. No-op before the first window."""
    bus = _living_bus()
    if bus is None:
        return
    bus.changed.emit(str(plugin_id), bool(enabled))


def plugin_ui_state(plugin_id: str, marketplace=None) -> str:
    """``shown``, ``gated``, or ``hidden`` for one plugin's contributed UI.

    Hidden when the plugin is not installed or its Enabled flag is off.
    Gated when it is enabled but the licence does not allow it: the section
    may show a ``not_available`` reason and must not show the form.
    Shown when it is installed, enabled, and the licence allows it.
    """
    from .marketplace import LocalPluginMarketplace

    market = (
        marketplace if marketplace is not None else LocalPluginMarketplace()
    )
    installed = any(
        row.get("id") == plugin_id for row in market.list_installed()
    )
    if not installed or not market.is_enabled(plugin_id):
        return "hidden"
    if not market.license_status(plugin_id).allowed:
        return "gated"
    return "shown"


def plugin_gate_reason(plugin_id: str, marketplace=None) -> str:
    """``not_available`` line for an enabled plugin the licence blocks."""
    from .marketplace import LocalPluginMarketplace

    market = (
        marketplace if marketplace is not None else LocalPluginMarketplace()
    )
    status = market.license_status(plugin_id)
    message = status.message or "License required"
    return f"not_available: {message}"
