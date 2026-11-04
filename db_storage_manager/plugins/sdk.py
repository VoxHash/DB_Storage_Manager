"""
Public Plugin SDK — stable APIs for third-party plugin authors.

Import from here (not from private modules) when writing plugins::

    from db_storage_manager.plugins.sdk import (
        Plugin,
        PluginMetadata,
        PluginType,
        PLUGIN_API_VERSION,
        load_manifest,
        validate_manifest,
    )

Manifest contract: a plugin directory must contain ``plugin.json`` and an
entry module referenced as ``module:ClassName``. Premium plugins add an optional
``license`` block (LicenseChain product id); see docs/api.md.
"""

from .base import Plugin, PluginManager, PluginMetadata, PluginType
from .licensing import (
    PluginLicenseError,
    PluginLicenseRequired,
)
from .pricing import PRICING_TIERS, SPONSORS_URL
from .manifest import (
    MANIFEST_FILENAME,
    PLUGIN_API_VERSION,
    LicenseRequirement,
    ManifestError,
    PluginManifest,
    load_manifest,
    validate_manifest,
)

__all__ = [
    "PLUGIN_API_VERSION",
    "MANIFEST_FILENAME",
    "PRICING_TIERS",
    "SPONSORS_URL",
    "LicenseRequirement",
    "ManifestError",
    "Plugin",
    "PluginManager",
    "PluginManifest",
    "PluginLicenseError",
    "PluginLicenseRequired",
    "PluginMetadata",
    "PluginType",
    "load_manifest",
    "validate_manifest",
]
