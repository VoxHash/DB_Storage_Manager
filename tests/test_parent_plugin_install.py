"""Install from Path accepts a parent folder of plugin.json directories."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from db_storage_manager.plugins.manifest import ManifestError, discover_plugin_roots
from db_storage_manager.premium_plugins import bundled_plugins_parent


REPO = Path(__file__).resolve().parents[1]
HELLO = REPO / "examples" / "plugins" / "hello_echo"


def _copy_plugin(dest: Path, plugin_id: str) -> None:
    shutil.copytree(HELLO, dest)
    manifest = json.loads((dest / "plugin.json").read_text(encoding="utf-8"))
    manifest["id"] = plugin_id
    manifest["name"] = plugin_id
    (dest / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    source = (dest / "plugin.py").read_text(encoding="utf-8")
    source = source.replace('plugin_id="hello_echo"', f'plugin_id="{plugin_id}"')
    (dest / "plugin.py").write_text(source, encoding="utf-8")


def test_premium_parent_has_no_root_manifest_and_lists_children():
    parent = bundled_plugins_parent()
    assert not (parent / "plugin.json").is_file()
    roots = discover_plugin_roots(parent)
    assert len(roots) >= 9
    assert all((root / "plugin.json").is_file() for root in roots)


def test_parent_installs_each_free_plugin(marketplace):
    mp, _store, _plugins = marketplace
    parent = _plugins.parent / "pack"
    parent.mkdir()
    _copy_plugin(parent / "one", "hello_one")
    _copy_plugin(parent / "two", "hello_two")
    (parent / "notes.txt").write_text("not a plugin", encoding="utf-8")

    summary = mp.install_from_path(parent)
    assert summary["multiple"] is True
    assert {row["id"] for row in summary["installed"]} == {"hello_one", "hello_two"}
    assert {row["id"] for row in mp.list_installed()} >= {"hello_one", "hello_two"}


def test_empty_folder_names_the_path(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "readme.txt").write_text("no plugin", encoding="utf-8")
    with pytest.raises(ManifestError, match="plugin.json"):
        discover_plugin_roots(empty)


def test_premium_parent_without_a_licence_explains(marketplace):
    mp, _store, _plugins = marketplace
    with pytest.raises(ManifestError, match="licence"):
        mp.install_from_path(bundled_plugins_parent())
