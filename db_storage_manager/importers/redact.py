"""Redact secrets from importer logs, API payloads, and reports."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|"
    r"passphrase|authorization|credential)",
    re.IGNORECASE,
)

_URL_USERINFO_RE = re.compile(r"(://)([^:/@\s]+)(:([^@/\s]*))?@")


def redact_url(url: str) -> str:
    """Replace userinfo in a URL with ``***:***``."""
    if not url:
        return url
    return _URL_USERINFO_RE.sub(r"\1***:***@", url)


def redact_text(text: str) -> str:
    """Best-effort redaction of passwords and URL credentials in free text."""
    if not text:
        return text
    out = redact_url(text)
    out = re.sub(
        r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=***",
        out,
    )
    return out


def redact_connection(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy safe for reports (no passwords / private keys)."""
    out: Dict[str, Any] = {}
    for key, value in connection.items():
        if _SECRET_KEY_RE.search(str(key)):
            out[key] = "***" if value else value
            continue
        if key == "connection_string" and isinstance(value, str):
            out[key] = redact_url(value)
            continue
        if key == "ssh_config" and isinstance(value, dict):
            out[key] = redact_connection(value)
            continue
        if isinstance(value, dict):
            out[key] = redact_connection(value)
        elif isinstance(value, list):
            out[key] = [
                redact_connection(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            out[key] = value
    return out


def redact_connections(connections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [redact_connection(c) for c in connections if isinstance(c, dict)]


def host_hint(host: Optional[str]) -> str:
    """Short host label for reports (keep hostname structure, no secrets)."""
    if not host:
        return ""
    return str(host).strip()


def summarize_profile(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Compact redacted summary for e2e / API responses."""
    ssh = connection.get("ssh_config") or {}
    return {
        "id": connection.get("id"),
        "name": connection.get("name"),
        "type": connection.get("type"),
        "host": host_hint(connection.get("host")),
        "port": connection.get("port"),
        "database": connection.get("database"),
        "username": connection.get("username"),
        "ssh_enabled": bool(ssh.get("enabled")),
        "ssh_host": host_hint(ssh.get("ssh_host")) if ssh else None,
        "has_password": bool(connection.get("password")),
        "source": (connection.get("extra") or {}).get("import_source"),
    }


def safe_urlparse_display(url: str) -> str:
    """Scheme + host + path only (no credentials)."""
    try:
        parsed = urlparse(url)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    except Exception:
        return redact_url(url)
