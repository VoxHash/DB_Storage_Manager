"""First-party premium plugins shipped beside the free core.

These are not built-ins. The built-in ``migration`` and ``data_comparison``
plugins stay free. Install a premium plugin from its directory (Plugins tab,
``plugins:manage``) and activate a LicenseChain licence before it can run.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["bundled_plugin_dir"]


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
