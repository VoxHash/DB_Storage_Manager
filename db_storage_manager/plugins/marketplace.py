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
from .licensing import (
    LicenseStatus,
    PluginLicenseError,
    PluginLicenseGate,
    PluginLicenseRequired,
)
from .manifest import (
    LicenseRequirement,
    ManifestError,
    discover_plugin_roots,
    load_manifest,
    parse_license_requirement,
)

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
        license_gate: Optional[PluginLicenseGate] = None,
    ):
        from ..config import PLUGINS_DIR

        self.plugins_dir = Path(plugins_dir) if plugins_dir else Path(PLUGINS_DIR)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        (self.plugins_dir / INSTALLED_SUBDIR).mkdir(parents=True, exist_ok=True)
        self.registry_path = self.plugins_dir / REGISTRY_FILENAME
        self.manager = manager or PluginManager()
        self.license_gate = license_gate or PluginLicenseGate()
        if self.manager.license_checker is None:
            self.manager.license_checker = self.require_license
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
                    "license": self._license_dict(entry),
                }
            )
        rows.sort(key=lambda r: r["id"])
        return rows

    # -- premium plugin licensing ----------------------------------------
    @staticmethod
    def _requirement_for_entry(entry: Dict[str, Any]) -> Optional[LicenseRequirement]:
        """Built-ins are always free; others follow ``manifest.license``."""
        if entry.get("source") == "builtin":
            return None
        raw = (entry.get("manifest") or {}).get("license")
        try:
            return parse_license_requirement(raw)
        except ManifestError:
            # A malformed block in the registry must fail closed, not run free.
            return LicenseRequirement(product_id="invalid-license-block")

    @staticmethod
    def _license_dict(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        requirement = LocalPluginMarketplace._requirement_for_entry(entry)
        return requirement.to_dict() if requirement else None

    def license_requirement(self, plugin_id: str) -> Optional[LicenseRequirement]:
        """Return the plugin's LicenseChain requirement, or ``None`` if free."""
        entry = self._read_registry()["plugins"].get(plugin_id)
        if not isinstance(entry, dict):
            return None
        return self._requirement_for_entry(entry)

    def license_status(self, plugin_id: str, *, network: bool = False) -> LicenseStatus:
        """License state for one plugin (cache-only unless ``network=True``)."""
        return self.license_gate.status(
            plugin_id, self.license_requirement(plugin_id), network=network
        )

    def require_license(self, plugin_id: str, *, network: bool = True) -> LicenseStatus:
        """Raise ``PluginLicenseError`` unless the plugin is free or licensed."""
        return self.license_gate.require(
            plugin_id, self.license_requirement(plugin_id), network=network
        )

    def activate_license(
        self, plugin_id: str, license_key: str, email: Optional[str] = None
    ) -> LicenseStatus:
        """Verify + store a LicenseChain key for an installed premium plugin."""
        requirement = self.license_requirement(plugin_id)
        if requirement is None:
            raise PluginLicenseError(
                f"plugin '{plugin_id}' does not require a license", code="free"
            )
        return self.license_gate.activate(plugin_id, requirement, license_key, email)

    def deactivate_license(self, plugin_id: str) -> bool:
        """Forget the stored key; the plugin is unloaded from the live manager."""
        removed = self.license_gate.deactivate(plugin_id)
        if self.manager.get_plugin(plugin_id) is not None:
            self.manager.set_enabled(plugin_id, False)
        return removed

    def get_enabled_map(self) -> Dict[str, bool]:
        """Load enabled flags from SecureStore settings (with defaults)."""
        from ..security.store import SecureStore

        settings = SecureStore().get_settings()
        prefs = normalize_plugins_prefs(settings.get("plugins"))
        return dict(prefs["enabled"])

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Persist enable/disable for a plugin id and update the live manager.

        Enabling a premium plugin requires an active LicenseChain license
        (``PluginLicenseError`` otherwise); disabling is always allowed.
        """
        from ..security.store import SecureStore

        if enabled:
            self.require_license(plugin_id)

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
            requirement = self._requirement_for_entry(row)
            if requirement is not None:
                # Startup never blocks on the network: trust the cached verification
                # (within the offline grace window) and revalidate on execute.
                if not self.license_gate.status(
                    plugin_id, requirement, network=False
                ).allowed:
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

    def install_from_path(
        self,
        source_path: Path,
        *,
        replace: bool = False,
        license_key: Optional[str] = None,
        license_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Copy a plugin directory into the local installed store and register it.

        A directory with its own ``plugin.json`` installs that plugin. A parent
        directory installs every child that has ``plugin.json``. Premium plugins
        (``plugin.json`` has a ``license`` block) are verified against
        LicenseChain *before* any plugin code is imported: pass ``license_key``
        (and ``license_email`` if the license has none), or have a valid license
        already stored. Otherwise ``PluginLicenseRequired`` /
        ``PluginLicenseError`` is raised and that plugin is not installed.

        One licence key is only applied when a single plugin directory was
        selected. A parent folder does not reuse one key across every product.
        """
        source_path = Path(source_path).resolve()
        roots = discover_plugin_roots(source_path)
        if len(roots) == 1:
            return self._install_plugin_directory(
                roots[0],
                replace=replace,
                license_key=license_key,
                license_email=license_email,
            )
        installed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        license_holds: List[PluginLicenseRequired] = []
        for root in roots:
            try:
                installed.append(
                    self._install_plugin_directory(
                        root,
                        replace=replace,
                        license_key=None,
                        license_email=None,
                    )
                )
            except PluginLicenseRequired as exc:
                license_holds.append(exc)
                skipped.append({"id": root.name, "reason": "license_required"})
            except (ManifestError, PluginLicenseError, OSError, RuntimeError) as exc:
                skipped.append({"id": root.name, "reason": str(exc)})
        if not installed:
            if license_holds and len(license_holds) == len(roots):
                names = ", ".join(item["id"] for item in skipped)
                raise ManifestError(
                    f"no plugin could be installed under {source_path}. "
                    f"Each of these needs its own licence: {names}. "
                    "Select one plugin directory and activate that licence, "
                    "or install the parent again after the licences are stored."
                )
            detail = "; ".join(
                f"{item['id']}: {item['reason']}" for item in skipped
            ) or "no plugin.json"
            raise ManifestError(
                f"no plugin could be installed under {source_path}. {detail}"
            )
        summary = dict(installed[0])
        summary["installed"] = installed
        summary["skipped"] = skipped
        summary["multiple"] = True
        return summary

    def _install_plugin_directory(
        self,
        root: Path,
        *,
        replace: bool = False,
        license_key: Optional[str] = None,
        license_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Install one directory that already contains ``plugin.json``."""
        root = Path(root).resolve()
        manifest = load_manifest(root)
        if manifest.license is not None:
            if license_key:
                self.license_gate.activate(
                    manifest.id, manifest.license, license_key, license_email
                )
            else:
                try:
                    self.license_gate.require(manifest.id, manifest.license)
                except PluginLicenseRequired as exc:
                    exc.plugin_name = manifest.name
                    raise
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

    def install_from_url(
        self,
        url: str,
        *,
        replace: bool = False,
        license_key: Optional[str] = None,
        license_email: Optional[str] = None,
    ) -> Dict[str, Any]:
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

            row = self.install_from_path(
                extract_dir,
                replace=replace,
                license_key=license_key,
                license_email=license_email,
            )
            # A parent archive installs every child. Each one came from this
            # URL, including the ones after the first.
            data = self._read_registry()
            installed_rows = row.get("installed") if row.get("multiple") else None
            if isinstance(installed_rows, list) and installed_rows:
                ids = [item.get("id") for item in installed_rows if item.get("id")]
            else:
                ids = [row["id"]] if row.get("id") else []
            stamped: List[Dict[str, Any]] = []
            for plugin_id in ids:
                entry = data["plugins"].get(plugin_id)
                if not isinstance(entry, dict):
                    continue
                entry["source"] = "url"
                entry["origin"] = url
                stamped.append(self._row_from_entry(entry))
            self._write_registry(data)
            if len(stamped) == 1 and not row.get("multiple"):
                return stamped[0]
            summary = dict(stamped[0]) if stamped else dict(row)
            summary["installed"] = stamped or list(installed_rows or [])
            summary["skipped"] = list(row.get("skipped") or [])
            summary["multiple"] = True
            summary["source"] = "url"
            return summary

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
        self._forget_enabled_pref(plugin_id)
        return True

    def _forget_enabled_pref(self, plugin_id: str) -> None:
        """Drop a user plugin's enabled flag so the next install starts enabled.

        Built-in defaults stay. A plugin that was disabled, uninstalled, and
        installed again would otherwise stay off because the old flag remained.
        """
        if plugin_id in {item["id"] for item in BUILTIN_PLUGINS}:
            return
        from ..security.store import SecureStore

        store = SecureStore()
        settings = store.get_settings()
        prefs = normalize_plugins_prefs(settings.get("plugins"))
        if plugin_id not in prefs["enabled"]:
            return
        del prefs["enabled"][plugin_id]
        settings["plugins"] = prefs
        store.set_settings(settings)

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
            "license": LocalPluginMarketplace._license_dict(entry),
        }
