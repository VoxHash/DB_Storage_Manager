"""
Plugin manifest (plugin.json) load and validation.

Stable contract for third-party plugins. See ``db_storage_manager.plugins.sdk``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import PluginType

PLUGIN_API_VERSION = "1.0"
MANIFEST_FILENAME = "plugin.json"

_VALID_TYPES = {t.value for t in PluginType}


class ManifestError(ValueError):
    """Raised when a plugin manifest is missing or invalid."""


@dataclass
class PluginManifest:
    """Validated plugin.json contents."""

    id: str
    name: str
    version: str
    author: str
    description: str
    plugin_type: str
    entry: str
    api_version: str = PLUGIN_API_VERSION
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "plugin_type": self.plugin_type,
            "entry": self.entry,
            "api_version": self.api_version,
            "dependencies": list(self.dependencies),
        }


def _require_str(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"manifest field '{key}' must be a non-empty string")
    return value.strip()


def validate_manifest(data: Dict[str, Any]) -> PluginManifest:
    """Validate a raw dict and return a ``PluginManifest``."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")

    plugin_id = _require_str(data, "id")
    if "/" in plugin_id or "\\" in plugin_id or ".." in plugin_id:
        raise ManifestError("manifest id must be a simple identifier")

    plugin_type = _require_str(data, "plugin_type")
    if plugin_type not in _VALID_TYPES:
        raise ManifestError(
            f"plugin_type must be one of: {', '.join(sorted(_VALID_TYPES))}"
        )

    entry = _require_str(data, "entry")
    if ":" not in entry:
        raise ManifestError("entry must be 'module:ClassName' relative to plugin root")

    api_version = data.get("api_version", PLUGIN_API_VERSION)
    if not isinstance(api_version, str) or not api_version.strip():
        raise ManifestError("api_version must be a non-empty string")
    api_version = api_version.strip()
    # Compatible: same major (before first '.')
    if api_version.split(".", 1)[0] != PLUGIN_API_VERSION.split(".", 1)[0]:
        raise ManifestError(
            f"api_version '{api_version}' incompatible with host "
            f"PLUGIN_API_VERSION '{PLUGIN_API_VERSION}'"
        )

    deps = data.get("dependencies", [])
    if deps is None:
        deps = []
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise ManifestError("dependencies must be a list of strings")

    return PluginManifest(
        id=plugin_id,
        name=_require_str(data, "name"),
        version=_require_str(data, "version"),
        author=_require_str(data, "author"),
        description=_require_str(data, "description"),
        plugin_type=plugin_type,
        entry=entry,
        api_version=api_version,
        dependencies=list(deps),
    )


def load_manifest(path: Path) -> PluginManifest:
    """Load and validate ``plugin.json`` from a plugin directory or file path."""
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    if not path.is_file():
        raise ManifestError(f"missing manifest: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc
    return validate_manifest(raw)


def find_plugin_root(path: Path) -> Path:
    """Return the directory that contains ``plugin.json`` (root or one child)."""
    path = Path(path).resolve()
    if (path / MANIFEST_FILENAME).is_file():
        return path
    if path.is_file() and path.name == MANIFEST_FILENAME:
        return path.parent
    if path.is_dir():
        children = [p for p in path.iterdir() if p.is_dir()]
        if len(children) == 1 and (children[0] / MANIFEST_FILENAME).is_file():
            return children[0]
    raise ManifestError(f"no {MANIFEST_FILENAME} found under {path}")


def parse_entry(entry: str) -> tuple[str, str]:
    """Split ``module:ClassName`` into module and class names."""
    module_name, _, class_name = entry.partition(":")
    if not module_name or not class_name:
        raise ManifestError("entry must be 'module:ClassName'")
    return module_name, class_name
