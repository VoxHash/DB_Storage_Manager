"""
Plugin registry for discovering and loading plugins
"""

import importlib
import pkgutil
from pathlib import Path
from typing import List, Dict, Any
from .base import Plugin, PluginType


class PluginRegistry:
    """Plugin registry for dynamic plugin loading"""

    def __init__(self, plugin_directory: str = "plugins"):
        self.plugin_directory = Path(plugin_directory)
        self.discovered_plugins: Dict[str, Dict[str, Any]] = {}

    def discover_plugins(self) -> List[Dict[str, Any]]:
        """Discover plugins in the plugin directory"""
        plugins = []
        
        if not self.plugin_directory.exists():
            return plugins
        
        for module_info in pkgutil.iter_modules([str(self.plugin_directory)]):
            try:
                module = importlib.import_module(f"{self.plugin_directory.name}.{module_info.name}")
                if hasattr(module, "PLUGIN_CLASS"):
                    plugin_class = getattr(module, "PLUGIN_CLASS")
                    if issubclass(plugin_class, Plugin):
                        plugins.append({
                            "name": module_info.name,
                            "class": plugin_class,
                            "module": module,
                        })
            except Exception:
                continue
        
        return plugins

    def load_plugin(self, plugin_info: Dict[str, Any]) -> Plugin:
        """Load a plugin from plugin info"""
        plugin_class = plugin_info["class"]
        # Plugin would be instantiated with proper metadata
        return plugin_class

