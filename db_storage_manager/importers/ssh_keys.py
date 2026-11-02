"""Import SSH private keys (+ optional metadata) into SSH-enabled connection profiles.

Looks beside the key for ``SSH.pub`` / ``*.pub``, ``VPS.txt``, ``DB.txt``, and
similar sidecar files used by ops folders (e.g. BrightAds ``connections/<site>/``).
Prefers referencing the private key path on disk; optionally can embed encrypted
key material via callers that write into SecureStore (never plaintext in git).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..ssh.tunnel import normalize_ssh_config

_PRIVATE_KEY_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "BEGIN DSA PRIVATE KEY",
    "BEGIN PRIVATE KEY",
)

_KEY_FILENAMES = (
    "KEY",
    "key",
    "id_ed25519",
    "id_rsa",
    "id_ecdsa",
    "id_dsa",
    "private_key",
    "private.key",
)

_PUB_FILENAMES = ("SSH.pub", "ssh.pub", "id_ed25519.pub", "id_rsa.pub", "KEY.pub")


def _is_private_key_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:200]
    except OSError:
        return False
    return any(marker in head for marker in _PRIVATE_KEY_MARKERS)


def find_private_key(directory: Path) -> Optional[Path]:
    """Locate a private key file inside ``directory``."""
    for name in _KEY_FILENAMES:
        candidate = directory / name
        if _is_private_key_file(candidate):
            return candidate
    # Any OpenSSH private key in the folder
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() not in {".pub", ".txt", ".md"}:
            if _is_private_key_file(path):
                return path
    return None


def find_public_key(directory: Path, private_key: Optional[Path] = None) -> Optional[Path]:
    for name in _PUB_FILENAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    if private_key is not None:
        sibling = private_key.with_suffix(private_key.suffix + ".pub")
        if sibling.is_file():
            return sibling
        sibling2 = Path(str(private_key) + ".pub")
        if sibling2.is_file():
            return sibling2
    for path in sorted(directory.glob("*.pub")):
        if path.is_file():
            return path
    return None


def _parse_kv_sidecar(text: str) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Parse simple ``Key: value`` / ``Key=value`` / INI-ish sidecars.

    Returns ``(flat_kv, sections)``.
    """
    result: Dict[str, str] = {}
    current_section: Optional[str] = None
    section_data: Dict[str, Dict[str, str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        section_match = re.match(r"^\[([^\]]+)\]\s*$", line)
        if section_match:
            current_section = section_match.group(1).strip()
            section_data.setdefault(current_section, {})
            continue
        match = re.match(
            r"^(?P<k>[A-Za-z][A-Za-z0-9_ .-]*?)\s*[:=]\s*(?P<v>.+)$", line
        )
        if not match:
            continue
        key = match.group("k").strip().lower().replace(" ", "_")
        value = match.group("v").strip()
        if current_section:
            section_data[current_section][key] = value
        else:
            result[key] = value
    return result, section_data


def parse_vps_sidecar(path: Path) -> Dict[str, Any]:
    """Extract bastion host / SSH username from VPS.txt-style files."""
    text = path.read_text(encoding="utf-8", errors="replace")
    host = None
    # Prefer IP/hostname from URL lines
    url_match = re.search(
        r"https?://([^/:]+)(?::(\d+))?", text, flags=re.IGNORECASE
    )
    if url_match:
        host = url_match.group(1)
    if not host:
        ip_match = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        if ip_match:
            host = ip_match.group(1)
    kv, _sections = _parse_kv_sidecar(text)
    username = kv.get("user") or kv.get("username") or kv.get("ssh_user")
    password = kv.get("password") or kv.get("passwd")
    return {
        "ssh_host": host,
        "ssh_username": username,
        "ssh_password": password,
        "panel_url": url_match.group(0) if url_match else None,
    }


def parse_db_sidecar(path: Path, site_hint: Optional[str] = None) -> Dict[str, Any]:
    """Extract MySQL/Postgres credentials from DB.txt-style files."""
    text = path.read_text(encoding="utf-8", errors="replace")
    kv, sections = _parse_kv_sidecar(text)

    chosen: Dict[str, str] = dict(kv)
    if sections and site_hint:
        # Prefer section matching folder / site name
        for name, data in sections.items():
            if name.lower() == site_hint.lower() or site_hint.lower() in name.lower():
                chosen = dict(data)
                break
        else:
            # First section as fallback
            chosen = dict(next(iter(sections.values())))
    elif sections:
        chosen = dict(next(iter(sections.values())))

    database = (
        chosen.get("database")
        or chosen.get("db")
        or chosen.get("dbname")
        or chosen.get("name")
    )
    username = (
        chosen.get("user")
        or chosen.get("username")
        or chosen.get("db_user")
        or chosen.get("login")
    )
    password = (
        chosen.get("password")
        or chosen.get("passwd")
        or chosen.get("pwd")
        or chosen.get("db_password")
    )
    engine = (chosen.get("type") or chosen.get("engine") or "mysql").lower()
    if engine in ("postgres", "pgsql", "postgresql"):
        engine = "postgresql"
        default_port = 5432
    elif engine in ("mariadb", "mysql"):
        engine = "mysql"
        default_port = 3306
    else:
        engine = "mysql"
        default_port = 3306

    port_raw = chosen.get("port")
    try:
        port = int(port_raw) if port_raw else default_port
    except ValueError:
        port = default_port

    return {
        "type": engine,
        "database": database,
        "username": username,
        "password": password,
        "port": port,
        "host": chosen.get("host") or "localhost",
    }


def _ssh_username_from_pubkey(pub_path: Optional[Path]) -> Optional[str]:
    if pub_path is None or not pub_path.is_file():
        return None
    try:
        line = pub_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if not line:
            return None
        parts = line[0].split()
        if len(parts) >= 3:
            comment = parts[-1]
            # comment often is username or username@host
            return comment.split("@", 1)[0] or None
    except OSError:
        return None
    return None


def resolve_ssh_import_paths(
    path: Path | str,
) -> Tuple[Path, Optional[Path], Path]:
    """Return ``(private_key, public_key, directory)`` for a key file or folder."""
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        directory = path
        private_key = find_private_key(directory)
        if private_key is None:
            raise FileNotFoundError(f"No SSH private key found in {directory}")
    elif path.is_file():
        private_key = path
        if not _is_private_key_file(private_key):
            raise ValueError(f"Not an SSH private key file: {path}")
        directory = path.parent
    else:
        raise FileNotFoundError(f"SSH key path not found: {path}")
    public_key = find_public_key(directory, private_key)
    return private_key, public_key, directory


def import_ssh_key_path(
    path: Path | str,
    *,
    name: Optional[str] = None,
    db_type: str = "mysql",
    remote_host: str = "localhost",
    remote_port: Optional[int] = None,
    ssh_host: Optional[str] = None,
    ssh_username: Optional[str] = None,
    ssh_port: int = 22,
    database: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    store_key_material: bool = False,
) -> Dict[str, Any]:
    """Build one SSH-enabled connection profile from a key file or folder.

    Sidecar ``VPS.txt`` / ``DB.txt`` values fill gaps when present. Private key
    material is referenced by absolute path unless ``store_key_material`` is True
    (then ``extra.ssh_private_key_pem`` holds the PEM for SecureStore encryption).
    """
    private_key, public_key, directory = resolve_ssh_import_paths(path)
    site_hint = directory.name

    vps: Dict[str, Any] = {}
    for vps_name in ("VPS.txt", "vps.txt", "bastion.txt", "ssh.txt"):
        candidate = directory / vps_name
        if candidate.is_file():
            vps = parse_vps_sidecar(candidate)
            break

    db_meta: Dict[str, Any] = {}
    for db_name in ("DB.txt", "db.txt", "database.txt", "mysql.txt"):
        candidate = directory / db_name
        if candidate.is_file():
            db_meta = parse_db_sidecar(candidate, site_hint=site_hint)
            break

    engine = (db_meta.get("type") or db_type or "mysql").lower()
    if engine in ("postgres", "pgsql"):
        engine = "postgresql"
    if engine == "mariadb":
        engine = "mysql"

    if remote_port is None:
        remote_port = int(db_meta.get("port") or (5432 if engine == "postgresql" else 3306))

    bastion_host = ssh_host or vps.get("ssh_host") or site_hint
    bastion_user = (
        ssh_username
        or vps.get("ssh_username")
        or _ssh_username_from_pubkey(public_key)
        or ""
    )

    db_name = database or db_meta.get("database") or site_hint.replace(".", "_")
    db_user = username or db_meta.get("username")
    db_pass = password if password is not None else db_meta.get("password")
    # DB host as seen from the app when tunnel is closed — keep localhost;
    # Test Connection / TunnelManager rewrites to the local forward endpoint.
    app_host = "localhost"
    app_port = remote_port

    profile_name = name or f"{site_hint} (SSH/{engine})"

    ssh_config = normalize_ssh_config(
        {
            "enabled": True,
            "ssh_host": bastion_host,
            "ssh_port": ssh_port,
            "ssh_username": bastion_user,
            "ssh_password": vps.get("ssh_password"),
            "ssh_key_path": str(private_key),
            "remote_host": remote_host or db_meta.get("host") or "localhost",
            "remote_port": remote_port,
        }
    )

    extra: Dict[str, Any] = {
        "import_source": "ssh_key",
        "import_path": str(directory),
        "ssh_key_path": str(private_key),
        "ssh_pub_path": str(public_key) if public_key else None,
        "site": site_hint,
    }
    if vps.get("panel_url"):
        extra["panel_url"] = vps["panel_url"]
    if store_key_material:
        # Caller persists via SecureStore — never write PEM to git / logs
        extra["ssh_private_key_pem"] = private_key.read_text(
            encoding="utf-8", errors="replace"
        )

    return {
        "id": str(uuid.uuid4()),
        "name": profile_name,
        "type": engine,
        "host": app_host,
        "port": app_port,
        "database": db_name,
        "username": db_user,
        "password": db_pass,
        "connection_string": None,
        "ssh_config": ssh_config,
        "extra": extra,
    }


def import_ssh_directory(
    path: Path | str,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Import SSH connection profile(s) from a directory (one primary key)."""
    return [import_ssh_key_path(path, **kwargs)]
