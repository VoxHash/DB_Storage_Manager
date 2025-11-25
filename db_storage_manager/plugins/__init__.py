"""
Plugin system for extensibility
"""

from .base import Plugin, PluginManager
from .registry import PluginRegistry

__all__ = ["Plugin", "PluginManager", "PluginRegistry"]

