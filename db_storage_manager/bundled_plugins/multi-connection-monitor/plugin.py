"""Health-check several connections the operator opted in. Rate limited."""

from __future__ import annotations

from typing import Any, Dict, Optional

from db_storage_manager.monitoring.multi_watch import watch
from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType


class MultiConnectionMonitorPlugin(Plugin):
    def __init__(self, metadata: Optional[PluginMetadata] = None):
        if metadata is None:
            metadata = PluginMetadata(
                name="Multi-connection monitor",
                version="1.0.0",
                author="VoxHash",
                description=(
                    "Poll health for connections the operator opted in. "
                    "Credentials stay in SecureStore."
                ),
                plugin_type=PluginType.PERFORMANCE_MONITORING,
                plugin_id="multi-connection-monitor",
            )
        super().__init__(metadata)

    def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        return watch(**kwargs)

    def cleanup(self) -> None:
        return None


PLUGIN_CLASS = MultiConnectionMonitorPlugin
