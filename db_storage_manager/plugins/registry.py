"""
Plugin registry for discovering and loading plugins.

Prefer :class:`db_storage_manager.plugins.marketplace.LocalPluginMarketplace`
for install / enable / disable. This class remains for directory discovery.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .base import Plugin
from .loader import PluginLoadError, load_plugin_from_directory, resolve_plugin_class
from .manifest import MANIFEST_FILENAME, ManifestError


class PluginRegistry:
    """Plugin registry for dynamic plugin loading from a directory."""

    def __init__(self, plugin_directory: str = "plugins"):
        self.plugin_directory = Path(plugin_directory)
        self.discovered_plugins: Dict[str, Dict[str, Any]] = {}

    def discover_plugins(self) -> List[Dict[str, Any]]:
        """Discover plugins in the plugin directory.

        Supports:
        - Subpackages with ``PLUGIN_CLASS`` (legacy in-tree layout)
        - Child directories containing ``plugin.json`` (SDK layout)
        """
        plugins: List[Dict[str, Any]] = []

        if not self.plugin_directory.exists():
            return plugins

        # Manifest-based directories
        for child in sorted(self.plugin_directory.iterdir()):
            if not child.is_dir():
                continue
            if (child / MANIFEST_FILENAME).is_file():
                try:
                    plugin = load_plugin_from_directory(child)
                except (PluginLoadError, ManifestError):
                    continue
                info = {
                    "name": plugin.metadata.plugin_id or plugin.metadata.name,
                    "class": type(plugin),
                    "path": str(child),
                    "instance": plugin,
                    "source": "manifest",
                }
                plugins.append(info)
                self.discovered_plugins[info["name"]] = info

        # Legacy module discovery (PLUGIN_CLASS)
        try:
            for module_info in pkgutil.iter_modules([str(self.plugin_directory)]):
                if module_info.name.startswith("_"):
                    continue
                try:
                    module = importlib.import_module(
                        f"{self.plugin_directory.name}.{module_info.name}"
                    )
                    if hasattr(module, "PLUGIN_CLASS"):
                        plugin_class = resolve_plugin_class(module)
                        info = {
                            "name": module_info.name,
                            "class": plugin_class,
                            "module": module,
                            "source": "module",
                        }
                        plugins.append(info)
                        self.discovered_plugins[module_info.name] = info
                except Exception:
                    continue
        except Exception:
            pass

        return plugins

    def load_plugin(self, plugin_info: Dict[str, Any]) -> Optional[Plugin]:
        """Load a plugin instance from discover_plugins() info."""
        if "instance" in plugin_info and isinstance(plugin_info["instance"], Plugin):
            return plugin_info["instance"]
        plugin_class: Type[Plugin] = plugin_info["class"]
        try:
            return plugin_class()
        except TypeError:
            return None
