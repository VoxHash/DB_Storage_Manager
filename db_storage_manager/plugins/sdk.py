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

Catalog and provider plugins stay on this API (1.0). They are opt-in: nothing
runs because the folder is present; the operator installs and enables them.
Data comes from a real catalog (``information_schema``, ``pg_catalog``,
``sqlite_master``) or the operator's provider API. Rule: no bundled credentials.
When the engine, plan or role cannot answer, return status
``not_available`` with a reason. Do not guess a pass or a failure.
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

NOT_AVAILABLE = "not_available"


def not_available(reason: str, **fields: object) -> dict:
    """Result when the engine, plan or role cannot answer. Do not guess."""
    report: dict = {"ok": False, "status": NOT_AVAILABLE, "reason": str(reason)}
    report.update(fields)
    return report

# Authoring bar for catalog / provider plugins. The docstring above is the
# contract; this tuple is what tests and reviews check for drift.
CATALOG_PLUGIN_RULES = (
    "opt-in",
    "real catalog",
    "provider API",
    "no bundled credentials",
    "not_available",
    "plan or role",
)

__all__ = [
    "CATALOG_PLUGIN_RULES",
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
    "not_available",
    "NOT_AVAILABLE",
    "validate_manifest",
]
