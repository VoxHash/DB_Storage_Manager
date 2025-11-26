"""
Base plugin system
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


class PluginType(Enum):
    """Plugin types"""

    MIGRATION = "migration"
    DATA_COMPARISON = "data_comparison"
    PERFORMANCE_MONITORING = "performance_monitoring"
    VISUALIZATION = "visualization"
    CUSTOM = "custom"


@dataclass
class PluginMetadata:
    """Plugin metadata"""

    name: str
    version: str
    author: str
    description: str
    plugin_type: PluginType
    dependencies: List[str] = None


class Plugin(ABC):
    """Base plugin class"""

    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self.enabled = True

    @abstractmethod
    def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize plugin"""
        pass

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """Execute plugin functionality"""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Cleanup plugin resources"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information"""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "author": self.metadata.author,
            "description": self.metadata.description,
            "type": self.metadata.plugin_type.value,
            "enabled": self.enabled,
        }


class PluginManager:
    """Plugin manager"""

    def __init__(self):
        self.plugins: Dict[str, Plugin] = {}
        self.context: Dict[str, Any] = {}

    def register_plugin(self, plugin: Plugin) -> bool:
        """Register a plugin"""
        if plugin.metadata.name in self.plugins:
            return False

        if plugin.initialize(self.context):
            self.plugins[plugin.metadata.name] = plugin
            return True
        return False

    def unregister_plugin(self, plugin_name: str) -> bool:
        """Unregister a plugin"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name].cleanup()
            del self.plugins[plugin_name]
            return True
        return False

    def get_plugin(self, plugin_name: str) -> Optional[Plugin]:
        """Get a plugin by name"""
        return self.plugins.get(plugin_name)

    def list_plugins(self, plugin_type: Optional[PluginType] = None) -> List[Plugin]:
        """List all plugins, optionally filtered by type"""
        plugins = list(self.plugins.values())
        if plugin_type:
            plugins = [p for p in plugins if p.metadata.plugin_type == plugin_type]
        return plugins

    def execute_plugin(self, plugin_name: str, *args, **kwargs) -> Any:
        """Execute a plugin"""
        plugin = self.plugins.get(plugin_name)
        if plugin and plugin.enabled:
            return plugin.execute(*args, **kwargs)
        return None

    def set_context(self, key: str, value: Any) -> None:
        """Set context value for plugins"""
        self.context[key] = value
