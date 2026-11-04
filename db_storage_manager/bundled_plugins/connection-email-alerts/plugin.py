"""Per-connection SMTP. Separate from the workstation-wide Settings profile."""

from __future__ import annotations

from typing import Any, Dict, Optional

from db_storage_manager.monitoring.alerts import Alert
from db_storage_manager.monitoring.connection_email import handle
from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType


class ConnectionEmailAlertsPlugin(Plugin):
    def __init__(self, metadata: Optional[PluginMetadata] = None):
        if metadata is None:
            metadata = PluginMetadata(
                name="Connection email alerts",
                version="1.0.0",
                author="VoxHash",
                description=(
                    "Opt-in SMTP for one saved connection. "
                    "The password stays in SecureStore."
                ),
                plugin_type=PluginType.CUSTOM,
                plugin_id="connection-email-alerts",
            )
        super().__init__(metadata)

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def execute(self, connection_id: str = "", alert: Optional[Alert] = None, **kwargs: Any) -> Dict[str, Any]:
        return handle(connection_id, alert, **kwargs)

    def cleanup(self) -> None:
        return None


PLUGIN_CLASS = ConnectionEmailAlertsPlugin
