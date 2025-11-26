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
        """Get application settings"""
        if not SETTINGS_FILE.exists():
            from ..config import DEFAULT_SETTINGS

            return DEFAULT_SETTINGS.copy()

        try:
            encrypted = SETTINGS_FILE.read_text(encoding="utf-8")
            return self._decrypt(encrypted)
        except Exception:
            from ..config import DEFAULT_SETTINGS

            return DEFAULT_SETTINGS.copy()

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
