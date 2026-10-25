"""
Secure storage for credentials and sensitive data using encryption
"""

import json
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional
from cryptography.fernet import Fernet
import os

from ..config import (
    CONNECTIONS_FILE,
    SETTINGS_FILE,
    SSH_KEYS_FILE,
    MASTER_KEY_FILE,
    USER_DATA_DIR,
)


class SecureStore:
    """Encrypted storage for sensitive data"""

    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._ensure_master_key()

    def _ensure_master_key(self) -> None:
        """Ensure master key exists or generate a new one"""
        if self._master_key:
            return

        if MASTER_KEY_FILE.exists():
            # Load existing master key
            self._master_key = MASTER_KEY_FILE.read_bytes()
        else:
            # Generate new master key
            self._master_key = Fernet.generate_key()
            MASTER_KEY_FILE.write_bytes(self._master_key)
            # Set restrictive permissions (Unix-like systems)
            if os.name != "nt":
                os.chmod(MASTER_KEY_FILE, 0o600)

    def _get_cipher(self) -> Fernet:
        """Get Fernet cipher instance"""
        if not self._master_key:
            self._ensure_master_key()
        return Fernet(self._master_key)

    def _encrypt(self, data: Any) -> str:
        """Encrypt data and return base64-encoded string"""
        cipher = self._get_cipher()
        json_data = json.dumps(data).encode("utf-8")
        encrypted = cipher.encrypt(json_data)
        return base64.b64encode(encrypted).decode("utf-8")

    def _decrypt(self, encrypted_data: str) -> Any:
        """Decrypt base64-encoded string and return data"""
        cipher = self._get_cipher()
        encrypted_bytes = base64.b64decode(encrypted_data.encode("utf-8"))
        decrypted = cipher.decrypt(encrypted_bytes)
        return json.loads(decrypted.decode("utf-8"))

    def get_settings(self) -> Dict[str, Any]:
        """Get application settings (merged with defaults for new keys)."""
        from ..config import DEFAULT_SETTINGS
        import copy

        defaults = copy.deepcopy(DEFAULT_SETTINGS)
        if not SETTINGS_FILE.exists():
            return defaults

        try:
            encrypted = SETTINGS_FILE.read_text(encoding="utf-8")
            loaded = self._decrypt(encrypted)
            if not isinstance(loaded, dict):
                return defaults
            merged = defaults
            merged.update(loaded)
            # Nested alert maps: keep defaults for missing metric/channel keys
            if isinstance(loaded.get("alert_thresholds"), dict):
                thresholds = copy.deepcopy(defaults["alert_thresholds"])
                for metric, levels in loaded["alert_thresholds"].items():
                    if isinstance(levels, dict):
                        thresholds.setdefault(metric, {}).update(levels)
                merged["alert_thresholds"] = thresholds
            if isinstance(loaded.get("alert_channels"), dict):
                channels = copy.deepcopy(defaults["alert_channels"])
                channels.update(loaded["alert_channels"])
                merged["alert_channels"] = channels
            if "dashboard_layout" in loaded:
                from ..dashboard_prefs import normalize_dashboard_layout

                merged["dashboard_layout"] = normalize_dashboard_layout(
                    loaded.get("dashboard_layout")
                )
            if "plugins" in loaded:
                from ..plugins.marketplace import normalize_plugins_prefs

                merged["plugins"] = normalize_plugins_prefs(loaded.get("plugins"))
            return merged
        except Exception:
            return defaults

    def set_settings(self, settings: Dict[str, Any]) -> None:
        """Save application settings"""
        encrypted = self._encrypt(settings)
        SETTINGS_FILE.write_text(encrypted, encoding="utf-8")
        # Set restrictive permissions
        if os.name != "nt":
            os.chmod(SETTINGS_FILE, 0o600)

    def get_connections(self) -> List[Dict[str, Any]]:
        """Get all database connections"""
        if not CONNECTIONS_FILE.exists():
            return []

        try:
            encrypted = CONNECTIONS_FILE.read_text(encoding="utf-8")
            return self._decrypt(encrypted)
        except Exception:
            return []

    def save_connections(self, connections: List[Dict[str, Any]]) -> None:
        """Save database connections"""
        encrypted = self._encrypt(connections)
        CONNECTIONS_FILE.write_text(encrypted, encoding="utf-8")
        # Set restrictive permissions
        if os.name != "nt":
            os.chmod(CONNECTIONS_FILE, 0o600)

    def get_ssh_keys(self) -> List[Dict[str, Any]]:
        """Get SSH keys"""
        if not SSH_KEYS_FILE.exists():
            return []

        try:
            encrypted = SSH_KEYS_FILE.read_text(encoding="utf-8")
            return self._decrypt(encrypted)
        except Exception:
            return []

    def save_ssh_keys(self, keys: List[Dict[str, Any]]) -> None:
        """Save SSH keys"""
        encrypted = self._encrypt(keys)
        SSH_KEYS_FILE.write_text(encrypted, encoding="utf-8")
        # Set restrictive permissions
        if os.name != "nt":
            os.chmod(SSH_KEYS_FILE, 0o600)

    def upsert_ssh_settings_for_connection(self, connection: Dict[str, Any]) -> None:
        """Persist SSH bastion settings for a connection into ssh-keys.enc.

        Connection profiles already store ``ssh_config`` (including password) via
        ``save_connections``. This index keeps a separate encrypted inventory of
        bastion host / key-path metadata keyed by connection id for reuse and
        audit without duplicating private key file contents on disk beyond the
        path the user selected.
        """
        ssh_config = connection.get("ssh_config") or {}
        if not ssh_config.get("enabled"):
            return

        connection_id = connection.get("id")
        if not connection_id:
            return

        entry = {
            "id": connection_id,
            "connection_id": connection_id,
            "connection_name": connection.get("name") or "",
            "ssh_host": ssh_config.get("ssh_host") or "",
            "ssh_port": ssh_config.get("ssh_port") or 22,
            "ssh_username": ssh_config.get("ssh_username") or "",
            "ssh_key_path": ssh_config.get("ssh_key_path") or None,
            # Password stays only in connections.enc; never mirror into ssh-keys.enc
            "has_password": bool(ssh_config.get("ssh_password")),
            "remote_host": ssh_config.get("remote_host") or "localhost",
            "remote_port": ssh_config.get("remote_port") or 5432,
        }

        keys = [k for k in self.get_ssh_keys() if k.get("connection_id") != connection_id]
        keys.append(entry)
        self.save_ssh_keys(keys)

    def remove_ssh_settings_for_connection(self, connection_id: str) -> None:
        """Drop SSH inventory entry for a deleted connection."""
        existing = self.get_ssh_keys()
        keys = [k for k in existing if k.get("connection_id") != connection_id]
        if len(keys) != len(existing):
            self.save_ssh_keys(keys)
