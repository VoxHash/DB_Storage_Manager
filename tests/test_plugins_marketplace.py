"""Tests for public plugin SDK and local marketplace registry."""

from __future__ import annotations

import os
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from db_storage_manager.plugins.base import PluginManager, PluginType
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.plugins.marketplace import (
    LocalPluginMarketplace,
    normalize_plugins_prefs,
)
from db_storage_manager.plugins.manifest import (
    PLUGIN_API_VERSION,
    ManifestError,
    load_manifest,
    validate_manifest,
)
from db_storage_manager.plugins.sdk import Plugin, PluginMetadata


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PLUGIN = REPO_ROOT / "examples" / "plugins" / "hello_echo"


@pytest.fixture
def marketplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_secure_store):
    """Marketplace rooted under tmp + SecureStore isolated via conftest."""
    store, data_dir = isolated_secure_store
    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "PLUGINS_DIR", plugins_dir)
    mp = LocalPluginMarketplace(plugins_dir=plugins_dir)
    return mp, store, plugins_dir


def test_sdk_api_version_and_validate_manifest():
    assert PLUGIN_API_VERSION == "1.0"
    manifest = validate_manifest(
        {
            "id": "demo",
            "name": "Demo",
            "version": "0.1.0",
            "author": "Tester",
            "description": "desc",
            "plugin_type": "custom",
            "entry": "plugin:DemoPlugin",
            "api_version": "1.0",
        }
    )
    assert manifest.id == "demo"
    with pytest.raises(ManifestError):
        validate_manifest({"id": "x"})
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1",
                "author": "a",
                "description": "d",
                "plugin_type": "not_a_type",
                "entry": "plugin:X",
            }
        )


def test_example_plugin_manifest_and_load():
    assert EXAMPLE_PLUGIN.is_dir()
    manifest = load_manifest(EXAMPLE_PLUGIN)
    assert manifest.id == "hello_echo"
    plugin = load_plugin_from_directory(EXAMPLE_PLUGIN)
    assert isinstance(plugin, Plugin)
    assert plugin.initialize({}) is True
    result = plugin.execute(message="ping")
    assert result["status"] == "success"
    assert result["echo"] == "ping"
    assert result["plugin_id"] == "hello_echo"
    plugin.cleanup()


def test_marketplace_lists_builtins(marketplace):
    mp, _store, _plugins_dir = marketplace
    rows = mp.list_installed()
    ids = {r["id"] for r in rows}
    assert "migration" in ids
    assert "data_comparison" in ids
    for row in rows:
        if row["id"] in {"migration", "data_comparison"}:
            assert row["source"] == "builtin"


def test_install_from_path_enable_disable_uninstall(marketplace):
    mp, store, plugins_dir = marketplace
    installed = mp.install_from_path(EXAMPLE_PLUGIN)
    assert installed["id"] == "hello_echo"
    assert (plugins_dir / "installed" / "hello_echo" / "plugin.json").is_file()

    rows = mp.list_installed()
    assert any(r["id"] == "hello_echo" and r["source"] == "path" for r in rows)

    mp.set_enabled("hello_echo", False)
    prefs = store.get_settings()["plugins"]
    assert prefs["enabled"]["hello_echo"] is False
    assert mp.is_enabled("hello_echo") is False

    mp.set_enabled("hello_echo", True)
    assert mp.is_enabled("hello_echo") is True

    manager = mp.load_into_manager(only_enabled=True)
    assert manager.get_plugin("hello_echo") is not None
    assert manager.execute_plugin("hello_echo", message="ok")["echo"] == "ok"

    assert mp.uninstall("hello_echo") is True
    assert not (plugins_dir / "installed" / "hello_echo").exists()
    assert all(r["id"] != "hello_echo" for r in mp.list_installed())


def test_cannot_uninstall_builtin(marketplace):
    mp, _store, _plugins_dir = marketplace
    mp.sync_builtins()
    with pytest.raises(ManifestError):
        mp.uninstall("migration")


def test_install_from_url_zip(marketplace, tmp_path: Path):
    mp, _store, plugins_dir = marketplace
    zip_path = tmp_path / "hello_echo.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in EXAMPLE_PLUGIN.rglob("*"):
            if path.is_file():
                zf.write(
                    path,
                    arcname=str(
                        Path("hello_echo") / path.relative_to(EXAMPLE_PLUGIN)
                    ),
                )

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        installed = mp.install_from_url(
            f"http://127.0.0.1:{port}/hello_echo.zip"
        )
        assert installed["id"] == "hello_echo"
        assert installed["source"] == "url"
        assert (plugins_dir / "installed" / "hello_echo" / "plugin.py").is_file()
    finally:
        server.shutdown()


def test_normalize_plugins_prefs():
    prefs = normalize_plugins_prefs({"enabled": {"migration": False, "extra": 1}})
    assert prefs["enabled"]["migration"] is False
    assert prefs["enabled"]["extra"] is True
    assert prefs["enabled"]["data_comparison"] is True
    assert normalize_plugins_prefs(None)["enabled"]["migration"] is True


def test_plugin_manager_set_enabled():
    manager = PluginManager()

    class Tiny(Plugin):
        def __init__(self):
            super().__init__(
                PluginMetadata(
                    name="tiny",
                    version="0.0.1",
                    author="t",
                    description="d",
                    plugin_type=PluginType.CUSTOM,
                    plugin_id="tiny",
                )
            )

        def initialize(self, context):
            return True

        def execute(self, *a, **k):
            return "ran"

        def cleanup(self):
            pass

    assert manager.register_plugin(Tiny()) is True
    assert manager.execute_plugin("tiny") == "ran"
    assert manager.set_enabled("tiny", False) is True
    assert manager.execute_plugin("tiny") is None


def test_secure_store_merges_plugins(isolated_secure_store):
    store, _data_dir = isolated_secure_store
    settings = store.get_settings()
    assert "plugins" in settings
    assert settings["plugins"]["enabled"]["migration"] is True
    settings["plugins"] = normalize_plugins_prefs(
        {"enabled": {"migration": False}}
    )
    store.set_settings(settings)
    reloaded = store.get_settings()
    assert reloaded["plugins"]["enabled"]["migration"] is False
    assert reloaded["plugins"]["enabled"]["data_comparison"] is True


def test_plugins_widget_offscreen_smoke(marketplace, monkeypatch):
    """Offscreen Qt smoke for the Plugins tab."""
    mp, _store, _plugins_dir = marketplace
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from db_storage_manager.gui.plugins import PluginsWidget

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: 0))

    app = QApplication.instance() or QApplication([])
    widget = PluginsWidget(marketplace=mp)
    assert widget.table.columnCount() == 7
    assert widget.table.rowCount() >= 2
    mp.install_from_path(EXAMPLE_PLUGIN)
    widget.refresh()
    ids = [
        widget.table.item(r, 0).text() for r in range(widget.table.rowCount())
    ]
    assert "hello_echo" in ids
    widget.close()
    app.processEvents()
