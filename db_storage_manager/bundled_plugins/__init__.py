"""Optional plugins shipped with the app. They are not built-ins.

Install from the Plugins tab (``plugins:manage``). Nothing here runs until
the operator installs and enables it.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["bundled_plugin_dir", "list_bundled_plugins"]


def bundled_plugin_dir(plugin_id: str) -> Path:
    if (
        not plugin_id
        or "/" in plugin_id
        or "\\" in plugin_id
        or ".." in plugin_id
    ):
        raise FileNotFoundError(f"no bundled plugin {plugin_id!r}")
    root = Path(__file__).resolve().parent / plugin_id
    if not (root / "plugin.json").is_file():
        raise FileNotFoundError(f"no bundled plugin {plugin_id}")
    return root


def list_bundled_plugins() -> list[Path]:
    parent = Path(__file__).resolve().parent
    found: list[Path] = []
    for child in sorted(parent.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and (child / "plugin.json").is_file():
            found.append(child)
    return found
