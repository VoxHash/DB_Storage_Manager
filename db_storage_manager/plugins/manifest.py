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
from .pricing import validate_pricing

PLUGIN_API_VERSION = "1.0"
MANIFEST_FILENAME = "plugin.json"

# LicenseChain Pay hosted checkout for a product (public, no seller secrets).
LICENSECHAIN_CHECKOUT_BASE = "https://pay.licensechain.app/checkout"

_VALID_TYPES = {t.value for t in PluginType}


class ManifestError(ValueError):
    """Raised when a plugin manifest is missing or invalid."""


@dataclass
class LicenseRequirement:
    """Optional ``license`` block of ``plugin.json`` (premium plugins).

    A plugin without this block is free. When ``required`` is true the host
    only installs / enables / runs the plugin while a LicenseChain license for
    ``product_id`` is active (see ``db_storage_manager.plugins.licensing``).
    """

    product_id: str
    required: bool = True
    purchase_url: str = ""
    provider: str = "licensechain"
    # Display-only mirror of the LicenseChain product price (see plugins.pricing).
    pricing: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "required": self.required,
            "provider": self.provider,
            "product_id": self.product_id,
            "purchase_url": self.purchase_url,
        }
        if self.pricing:
            data["pricing"] = dict(self.pricing)
        return data


def parse_license_requirement(raw: Any) -> Optional[LicenseRequirement]:
    """Validate the optional ``license`` object; ``None`` means a free plugin."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError("license must be a JSON object")
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ManifestError("license.required must be true or false")
    provider = raw.get("provider", "licensechain")
    if provider != "licensechain":
        raise ManifestError("license.provider must be 'licensechain'")
    if not required:
        return None
    product_id = raw.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ManifestError(
            "license.product_id must be the LicenseChain product id"
        )
    product_id = product_id.strip()
    if not all(ch.isalnum() or ch in "-_" for ch in product_id):
        raise ManifestError("license.product_id contains invalid characters")
    purchase_url = raw.get("purchase_url")
    if purchase_url is None or purchase_url == "":
        purchase_url = f"{LICENSECHAIN_CHECKOUT_BASE}/{product_id}"
    if not isinstance(purchase_url, str) or not purchase_url.startswith(
        "https://"
    ):
        raise ManifestError("license.purchase_url must be an https URL")
    try:
        pricing = validate_pricing(raw.get("pricing"))
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc
    return LicenseRequirement(
        product_id=product_id,
        required=True,
        purchase_url=purchase_url,
        provider=provider,
        pricing=pricing,
    )


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
    license: Optional[LicenseRequirement] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
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
        if self.license is not None:
            data["license"] = self.license.to_dict()
        return data


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
        license=parse_license_requirement(data.get("license")),
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
