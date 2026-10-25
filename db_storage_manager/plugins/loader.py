"""
Load plugin classes from package modules or filesystem directories.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, Type

from .base import Plugin, PluginMetadata, PluginType
from .manifest import PluginManifest, load_manifest, parse_entry


class PluginLoadError(RuntimeError):
    """Raised when a plugin module or class cannot be loaded."""


def _metadata_from_manifest(manifest: PluginManifest) -> PluginMetadata:
    return PluginMetadata(
        name=manifest.name,
        version=manifest.version,
        author=manifest.author,
        description=manifest.description,
        plugin_type=PluginType(manifest.plugin_type),
        dependencies=list(manifest.dependencies),
        plugin_id=manifest.id,
    )


def load_module_from_path(module_name: str, file_path: Path) -> ModuleType:
    """Import a Python module from an absolute file path under a unique name."""
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise PluginLoadError(f"module file not found: {file_path}")
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"cannot create import spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise PluginLoadError(f"failed to import {file_path}: {exc}") from exc
    return module


def resolve_plugin_class(
    module: ModuleType, class_name: Optional[str] = None
) -> Type[Plugin]:
    """Resolve ``PLUGIN_CLASS`` or a named class from a loaded module."""
    if class_name:
        if not hasattr(module, class_name):
            raise PluginLoadError(f"module has no class '{class_name}'")
        plugin_class = getattr(module, class_name)
    elif hasattr(module, "PLUGIN_CLASS"):
        plugin_class = getattr(module, "PLUGIN_CLASS")
    else:
        raise PluginLoadError("module must define PLUGIN_CLASS or entry class")

    if not isinstance(plugin_class, type) or not issubclass(plugin_class, Plugin):
        raise PluginLoadError("entry must be a Plugin subclass")
    return plugin_class


def instantiate_plugin(plugin_class: Type[Plugin], manifest: PluginManifest) -> Plugin:
    """Create a plugin instance, injecting metadata when the constructor accepts it."""
    metadata = _metadata_from_manifest(manifest)
    try:
        return plugin_class(metadata)
    except TypeError:
        instance = plugin_class()
        instance.metadata = metadata
        return instance


def load_plugin_from_directory(plugin_dir: Path) -> Plugin:
    """Load and instantiate a plugin from a directory containing ``plugin.json``."""
    plugin_dir = Path(plugin_dir).resolve()
    manifest = load_manifest(plugin_dir)
    module_name, class_name = parse_entry(manifest.entry)
    module_file = plugin_dir / f"{module_name.replace('.', '/')}.py"
    if not module_file.is_file():
        # allow package layout: module/__init__.py
        pkg_init = plugin_dir / module_name.replace(".", "/") / "__init__.py"
        if pkg_init.is_file():
            module_file = pkg_init
        else:
            raise PluginLoadError(
                f"entry module file not found for '{module_name}' under {plugin_dir}"
            )
    unique = f"dsm_plugin_{manifest.id}_{module_name.replace('.', '_')}"
    module = load_module_from_path(unique, module_file)
    plugin_class = resolve_plugin_class(module, class_name)
    return instantiate_plugin(plugin_class, manifest)


def load_builtin_plugin_class(module_qualname: str) -> Type[Plugin]:
    """Import a built-in plugin module and return its ``PLUGIN_CLASS``."""
    try:
        module = importlib.import_module(module_qualname)
    except Exception as exc:
        raise PluginLoadError(f"cannot import builtin {module_qualname}: {exc}") from exc
    return resolve_plugin_class(module)


def builtin_manifest_from_class(plugin_class: Type[Plugin]) -> PluginManifest:
    """Build a manifest snapshot from a builtin Plugin subclass (no-arg ctor)."""
    instance = plugin_class()
    meta = instance.metadata
    plugin_id = meta.plugin_id or meta.name
    return PluginManifest(
        id=plugin_id,
        name=meta.name,
        version=meta.version,
        author=meta.author,
        description=meta.description,
        plugin_type=meta.plugin_type.value,
        entry=f"{plugin_class.__module__.rsplit('.', 1)[-1]}:{plugin_class.__name__}",
        dependencies=list(meta.dependencies or []),
    )


def plugin_info_dict(plugin: Plugin, **extra: Any) -> dict:
    """Merge ``plugin.get_info()`` with extra marketplace fields."""
    info = plugin.get_info()
    info.update(extra)
    return info
