"""First-party premium plugins shipped beside the free core.

These are not built-ins. The built-in ``migration`` and ``data_comparison``
plugins stay free. Install a premium plugin from its directory (Plugins tab,
``plugins:manage``) and activate a LicenseChain licence before it can run.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "bundled_plugin_dir",
    "bundled_plugins_parent",
    "list_bundled_premium_plugins",
]


def bundled_plugin_dir(plugin_id: str) -> Path:
    """Directory that contains ``plugin.json`` for a bundled premium plugin."""
    if (
        not plugin_id
        or "/" in plugin_id
        or "\\" in plugin_id
        or ".." in plugin_id
    ):
        raise FileNotFoundError(f"no bundled premium plugin {plugin_id!r}")
    root = Path(__file__).resolve().parent / plugin_id
    if not (root / "plugin.json").is_file():
        raise FileNotFoundError(f"no bundled premium plugin {plugin_id}")
    return root


def bundled_plugins_parent() -> Path:
    """Directory that contains one subdirectory per bundled premium plugin."""
    return Path(__file__).resolve().parent


def list_bundled_premium_plugins() -> list[Path]:
    """Premium plugin directories shipped with the app, each with plugin.json."""
    parent = bundled_plugins_parent()
    found: list[Path] = []
    for child in sorted(parent.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and (child / "plugin.json").is_file():
            found.append(child)
    return found
