"""Strip secrets from connection profiles for REST responses."""

from __future__ import annotations

from typing import Any, Dict, List

_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "encryptionKey",
    "encryption_key",
    "ssh_password",
    "passphrase",
    "private_key",
    "privateKey",
}


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_connection(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_connection(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy safe for JSON API clients (no passwords / keys)."""
    out: Dict[str, Any] = {}
    for key, value in connection.items():
        if key.lower() in {k.lower() for k in _SECRET_KEYS} or key in _SECRET_KEYS:
            if value:
                out[key] = "***"
            else:
                out[key] = value
            continue
        if key == "ssh_config" and isinstance(value, dict):
            ssh = sanitize_connection(value)
            out[key] = ssh
            continue
        if isinstance(value, dict):
            out[key] = sanitize_connection(value)
        elif isinstance(value, list):
            out[key] = [sanitize_value(item) for item in value]
        else:
            out[key] = value
    return out


def sanitize_connections(connections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [sanitize_connection(c) for c in connections if isinstance(c, dict)]
