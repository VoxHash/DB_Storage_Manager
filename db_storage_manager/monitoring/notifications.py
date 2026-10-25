"""
Notification channels for monitoring alerts.

Channels fire when AlertManager emits a new alert. Desktop delivery uses a
caller-provided handler (typically QSystemTrayIcon.showMessage); in-app
delivery appends to a durable in-memory log the Monitoring UI can display.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .alerts import Alert

DEFAULT_ALERT_CHANNELS: Dict[str, bool] = {
    "desktop": True,
    "in_app": True,
}

DesktopHandler = Callable[[str, str, str], None]


class NotificationDispatcher:
    """Route alerts to enabled notification channels."""

    def __init__(self, channels: Optional[Dict[str, bool]] = None):
        self.channels: Dict[str, bool] = dict(DEFAULT_ALERT_CHANNELS)
        if channels:
            self.configure(channels)
        self.in_app_log: List[Dict[str, Any]] = []
        self.delivered: List[Dict[str, Any]] = []
        self._desktop_handler: Optional[DesktopHandler] = None

    def configure(self, channels: Dict[str, bool]) -> None:
        """Update which channels are enabled (unknown keys ignored)."""
        for key in DEFAULT_ALERT_CHANNELS:
            if key in channels:
                self.channels[key] = bool(channels[key])

    def set_desktop_handler(self, handler: Optional[DesktopHandler]) -> None:
        """Register OS/desktop notification delivery (title, message, severity)."""
        self._desktop_handler = handler

    def get_channels(self) -> Dict[str, bool]:
        return dict(self.channels)

    def clear_in_app_log(self) -> None:
        self.in_app_log.clear()

    def notify(self, alert: Alert) -> List[str]:
        """Deliver alert on every enabled channel. Returns channel names that fired."""
        fired: List[str] = []
        severity = alert.severity.value
        record_base = {
            "alert_id": alert.id,
            "title": alert.title,
            "message": alert.message,
            "severity": severity,
            "source": alert.source,
            "timestamp": datetime.now().isoformat(),
        }

        if self.channels.get("in_app", True):
            entry = {**record_base, "channel": "in_app"}
            self.in_app_log.append(entry)
            self.delivered.append(entry)
            fired.append("in_app")

        if self.channels.get("desktop", True):
            entry = {**record_base, "channel": "desktop"}
            if self._desktop_handler is not None:
                try:
                    self._desktop_handler(alert.title, alert.message, severity)
                    entry["delivered"] = True
                except Exception as exc:
                    entry["delivered"] = False
                    entry["error"] = str(exc)
            else:
                # No OS handler yet — still record the attempt so tests/UI can assert.
                entry["delivered"] = False
                entry["error"] = "no_desktop_handler"
            self.delivered.append(entry)
            fired.append("desktop")

        return fired
