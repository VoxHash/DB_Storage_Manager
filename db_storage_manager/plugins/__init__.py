"""
Plugin system for extensibility.

Public authoring API: ``db_storage_manager.plugins.sdk``
Local marketplace: ``db_storage_manager.plugins.marketplace``
"""

from .base import Plugin, PluginManager, PluginMetadata, PluginType
from .marketplace import LocalPluginMarketplace, normalize_plugins_prefs
from .manifest import PLUGIN_API_VERSION, ManifestError, load_manifest
from .registry import PluginRegistry

__all__ = [
    "PLUGIN_API_VERSION",
    "LocalPluginMarketplace",
    "ManifestError",
    "Plugin",
    "PluginManager",
    "PluginMetadata",
    "PluginRegistry",
    "PluginType",
    "load_manifest",
    "normalize_plugins_prefs",
]
