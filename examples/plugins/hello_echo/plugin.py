"""
Example third-party plugin for DB Storage Manager.

Install via the Plugins tab (Install from Path) or::

    from db_storage_manager.plugins.marketplace import LocalPluginMarketplace
    from pathlib import Path
    LocalPluginMarketplace().install_from_path(Path("examples/plugins/hello_echo"))
"""

from __future__ import annotations

from typing import Any, Dict

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType


class HelloEchoPlugin(Plugin):
    """Minimal custom plugin that echoes a message."""

    def __init__(self, metadata: PluginMetadata | None = None):
        if metadata is None:
            metadata = PluginMetadata(
                name="Hello Echo",
                version="1.0.0",
                author="VoxHash Technologies",
                description="Example SDK plugin that echoes a message",
                plugin_type=PluginType.CUSTOM,
                plugin_id="hello_echo",
            )
        super().__init__(metadata)

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, message: str = "hello", **kwargs: Any) -> Dict[str, Any]:
        return {
            "status": "success",
            "echo": message,
            "plugin_id": self.metadata.plugin_id or self.metadata.name,
            "context_keys": sorted(self._context.keys()) if hasattr(self, "_context") else [],
        }

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = HelloEchoPlugin
