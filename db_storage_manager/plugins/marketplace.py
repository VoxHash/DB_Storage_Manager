"""
Local plugin marketplace / registry.

Discovers built-in plugins, installs third-party plugins from a filesystem path
or HTTP(S) URL (zip / tar.gz), and persists enable/disable state. There is no
remote catalog with placeholder listings — a public store can plug into the
same registry later.
"""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .base import Plugin, PluginManager
from .loader import (
    PluginLoadError,
    builtin_manifest_from_class,
    load_builtin_plugin_class,
    load_plugin_from_directory,
)
from .manifest import ManifestError, find_plugin_root, load_manifest

BUILTIN_PLUGINS = (
    {
        "id": "migration",
        "module": "db_storage_manager.plugins.migration",
    },
    {
        "id": "data_comparison",
        "module": "db_storage_manager.plugins.data_comparison",
    },
)

REGISTRY_FILENAME = "registry.json"
INSTALLED_SUBDIR = "installed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_plugins_prefs() -> Dict[str, Any]:
    """Default SecureStore ``plugins`` settings blob."""
    return {
        "enabled": {
            "migration": True,
            "data_comparison": True,
        }
    }


def normalize_plugins_prefs(raw: Any) -> Dict[str, Any]:
    """Merge raw settings with defaults for the ``plugins`` key."""
    base = default_plugins_prefs()
    if not isinstance(raw, dict):
        return base
    enabled = dict(base["enabled"])
    raw_enabled = raw.get("enabled")
    if isinstance(raw_enabled, dict):
        for key, value in raw_enabled.items():
            if isinstance(key, str):
                enabled[key] = bool(value)
    return {"enabled": enabled}


class LocalPluginMarketplace:
    """Filesystem-backed local plugin registry and installer."""

    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        manager: Optional[PluginManager] = None,
    ):
        from ..config import PLUGINS_DIR

        self.plugins_dir = Path(plugins_dir) if plugins_dir else Path(PLUGINS_DIR)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        (self.plugins_dir / INSTALLED_SUBDIR).mkdir(parents=True, exist_ok=True)
        self.registry_path = self.plugins_dir / REGISTRY_FILENAME
        self.manager = manager or PluginManager()
        self._ensure_registry()

    def _ensure_registry(self) -> None:
        if not self.registry_path.exists():
            self._write_registry({"schema_version": 1, "plugins": {}})

    def _read_registry(self) -> Dict[str, Any]:
        self._ensure_registry()
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"schema_version": 1, "plugins": {}}
        if not isinstance(data, dict):
            data = {"schema_version": 1, "plugins": {}}
        plugins = data.get("plugins")
        if not isinstance(plugins, dict):
            data["plugins"] = {}
        data.setdefault("schema_version", 1)
        return data

    def _write_registry(self, data: Dict[str, Any]) -> None:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def sync_builtins(self) -> None:
        """Ensure built-in plugins appear in the local registry."""
        data = self._read_registry()
        changed = False
        for item in BUILTIN_PLUGINS:
            plugin_id = item["id"]
            try:
                plugin_class = load_builtin_plugin_class(item["module"])
                manifest = builtin_manifest_from_class(plugin_class)
            except PluginLoadError:
                continue
            entry = {
                "id": plugin_id,
                "source": "builtin",
                "module": item["module"],
                "path": None,
                "origin": item["module"],
                "installed_at": data.get("plugins", {})
                .get(plugin_id, {})
                .get("installed_at", _utc_now()),
                "manifest": manifest.to_dict(),
            }
            existing = data["plugins"].get(plugin_id)
            if existing != entry:
                # Preserve installed_at if already present
                if existing and existing.get("installed_at"):
                    entry["installed_at"] = existing["installed_at"]
                data["plugins"][plugin_id] = entry
                changed = True
        if changed:
            self._write_registry(data)

    def list_installed(self) -> List[Dict[str, Any]]:
        """Return registry entries (builtins + user installs), sorted by id."""
        self.sync_builtins()
        data = self._read_registry()
        rows = []
        for plugin_id, entry in data["plugins"].items():
            if not isinstance(entry, dict):
                continue
            manifest = entry.get("manifest") or {}
            rows.append(
                {
                    "id": plugin_id,
                    "name": manifest.get("name", plugin_id),
                    "version": manifest.get("version", ""),
                    "author": manifest.get("author", ""),
                    "description": manifest.get("description", ""),
                    "plugin_type": manifest.get("plugin_type", "custom"),
                    "source": entry.get("source", "unknown"),
                    "path": entry.get("path"),
                    "origin": entry.get("origin"),
                    "installed_at": entry.get("installed_at"),
                    "manifest": manifest,
                }
            )
        rows.sort(key=lambda r: r["id"])
        return rows

    def get_enabled_map(self) -> Dict[str, bool]:
        """Load enabled flags from SecureStore settings (with defaults)."""
        from ..security.store import SecureStore

        settings = SecureStore().get_settings()
        prefs = normalize_plugins_prefs(settings.get("plugins"))
        return dict(prefs["enabled"])

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Persist enable/disable for a plugin id and update the live manager."""
        from ..security.store import SecureStore

        store = SecureStore()
        settings = store.get_settings()
        prefs = normalize_plugins_prefs(settings.get("plugins"))
        prefs["enabled"][plugin_id] = bool(enabled)
        settings["plugins"] = prefs
        store.set_settings(settings)
        self.manager.set_enabled(plugin_id, enabled)

    def is_enabled(self, plugin_id: str) -> bool:
        enabled = self.get_enabled_map()
        return bool(enabled.get(plugin_id, True))

    def load_into_manager(self, only_enabled: bool = True) -> PluginManager:
        """Instantiate registered plugins into ``self.manager``."""
        enabled_map = self.get_enabled_map()
        for row in self.list_installed():
            plugin_id = row["id"]
            enabled = bool(enabled_map.get(plugin_id, True))
            if only_enabled and not enabled:
                continue
            if self.manager.get_plugin(plugin_id) is not None:
                self.manager.set_enabled(plugin_id, enabled)
                continue
            try:
                plugin = self._instantiate(row)
            except (PluginLoadError, ManifestError, TypeError, ValueError):
                continue
            plugin.enabled = enabled
            self.manager.register_plugin(plugin)
            self.manager.set_enabled(plugin_id, enabled)
        return self.manager

    def _instantiate(self, row: Dict[str, Any]) -> Plugin:
        source = row.get("source")
        if source == "builtin":
            module = row.get("origin") or (
                next(
                    (b["module"] for b in BUILTIN_PLUGINS if b["id"] == row["id"]),
                    None,
                )
            )
            if not module:
                raise PluginLoadError(f"unknown builtin plugin {row['id']}")
            plugin_class = load_builtin_plugin_class(module)
            instance = plugin_class()
            instance.metadata.plugin_id = row["id"]
            return instance
        path = row.get("path")
        if not path:
            raise PluginLoadError(f"plugin {row['id']} has no install path")
        return load_plugin_from_directory(Path(path))

    def install_from_path(self, source_path: Path, *, replace: bool = False) -> Dict[str, Any]:
        """Copy a plugin directory into the local installed store and register it."""
        source_path = Path(source_path).resolve()
        root = find_plugin_root(source_path)
        manifest = load_manifest(root)
        # Verify the plugin loads before copying
        load_plugin_from_directory(root)

        data = self._read_registry()
        if manifest.id in data["plugins"] and not replace:
            existing = data["plugins"][manifest.id]
            if existing.get("source") == "builtin":
                raise ManifestError(
                    f"cannot overwrite built-in plugin id '{manifest.id}'"
                )
            raise ManifestError(
                f"plugin '{manifest.id}' already installed (use replace=True)"
            )

        dest = self.plugins_dir / INSTALLED_SUBDIR / manifest.id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(root, dest)

        entry = {
            "id": manifest.id,
            "source": "path",
            "module": None,
            "path": str(dest),
            "origin": str(root),
            "installed_at": _utc_now(),
            "manifest": manifest.to_dict(),
        }
        data["plugins"][manifest.id] = entry
        self._write_registry(data)

        # Default: newly installed plugins are enabled
        prefs_enabled = self.get_enabled_map()
        if manifest.id not in prefs_enabled:
            self.set_enabled(manifest.id, True)

        # Hot-register if manager is empty for this id
        if self.manager.get_plugin(manifest.id) is not None:
            self.manager.unregister_plugin(manifest.id)
        plugin = load_plugin_from_directory(dest)
        plugin.enabled = self.is_enabled(manifest.id)
        self.manager.register_plugin(plugin)
        return self._row_from_entry(entry)

    def install_from_url(self, url: str, *, replace: bool = False) -> Dict[str, Any]:
        """Download a zip/tar.gz plugin archive from http(s) and install it."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ManifestError("install URL must use http or https")
        if not parsed.netloc:
            raise ManifestError("install URL is missing a host")

        suffix = Path(parsed.path).suffix.lower()
        with tempfile.TemporaryDirectory(prefix="dsm-plugin-") as tmp:
            tmp_path = Path(tmp)
            archive_name = Path(parsed.path).name or "plugin-archive"
            archive_path = tmp_path / archive_name
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    archive_path.write_bytes(response.read())
            except urllib.error.URLError as exc:
                raise ManifestError(f"failed to download plugin: {exc}") from exc

            extract_dir = tmp_path / "extracted"
            extract_dir.mkdir()
            lower_name = archive_path.name.lower()
            try:
                if zipfile.is_zipfile(archive_path) or suffix == ".zip":
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        zf.extractall(extract_dir)
                elif tarfile.is_tarfile(archive_path) or lower_name.endswith(
                    (".tar.gz", ".tgz", ".tar")
                ):
                    with tarfile.open(archive_path, "r:*") as tf:
                        tf.extractall(extract_dir)
                else:
                    raise ManifestError(
                        "URL must point to a .zip or .tar.gz plugin archive"
                    )
            except (zipfile.BadZipFile, tarfile.TarError) as exc:
                raise ManifestError(f"invalid plugin archive: {exc}") from exc

            root = find_plugin_root(extract_dir)
            row = self.install_from_path(root, replace=replace)
            # Re-stamp source/origin for URL installs
            data = self._read_registry()
            entry = data["plugins"][row["id"]]
            entry["source"] = "url"
            entry["origin"] = url
            data["plugins"][row["id"]] = entry
            self._write_registry(data)
            return self._row_from_entry(entry)

    def uninstall(self, plugin_id: str) -> bool:
        """Remove a user-installed plugin (builtins cannot be uninstalled)."""
        data = self._read_registry()
        entry = data["plugins"].get(plugin_id)
        if not entry:
            return False
        if entry.get("source") == "builtin":
            raise ManifestError("built-in plugins cannot be uninstalled")
        path = entry.get("path")
        if path:
            dest = Path(path)
            if dest.exists() and dest.is_dir():
                # Only delete under our installed/ tree
                installed_root = (self.plugins_dir / INSTALLED_SUBDIR).resolve()
                try:
                    dest.resolve().relative_to(installed_root)
                    shutil.rmtree(dest)
                except ValueError:
                    pass
        del data["plugins"][plugin_id]
        self._write_registry(data)
        if self.manager.get_plugin(plugin_id) is not None:
            self.manager.unregister_plugin(plugin_id)
        return True

    @staticmethod
    def _row_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        manifest = entry.get("manifest") or {}
        return {
            "id": entry.get("id"),
            "name": manifest.get("name", entry.get("id")),
            "version": manifest.get("version", ""),
            "author": manifest.get("author", ""),
            "description": manifest.get("description", ""),
            "plugin_type": manifest.get("plugin_type", "custom"),
            "source": entry.get("source"),
            "path": entry.get("path"),
            "origin": entry.get("origin"),
            "installed_at": entry.get("installed_at"),
            "manifest": manifest,
        }
