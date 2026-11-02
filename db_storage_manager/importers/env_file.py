"""Parse platform ``.env`` files into ConnectionConfig-shaped profiles.

Recognizes common keys from Supabase, Laravel, Prisma, Django, and generic
Postgres/MySQL stacks: ``DATABASE_URL``, ``DIRECT_URL``, ``DATABASE_URL_UNPOOLED``,
``DB_*``, ``POSTGRES_*``, ``MYSQL_*``, ``SUPABASE_*`` (URL hints only — service
role keys are never treated as DB passwords).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

# Ordered preference for primary vs alternate profiles
_URL_KEYS_PRIMARY = (
    "DIRECT_URL",
    "DATABASE_URL_UNPOOLED",
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_PRISMA_URL",
    "MYSQL_URL",
    "DB_URL",
)

_URL_KEYS_ALL = _URL_KEYS_PRIMARY + (
    "POSTGRES_URL_NON_POOLING",
    "SHADOW_DATABASE_URL",
)

_SCHEME_TO_TYPE = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "pgsql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mongodb": "mongodb",
    "mongodb+srv": "mongodb",
    "redis": "redis",
    "rediss": "redis",
    "sqlite": "sqlite",
    "mssql": "sqlserver",
    "sqlserver": "sqlserver",
}

_DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "mongodb": 27017,
    "redis": 6379,
    "sqlserver": 1433,
    "sqlite": None,
}

_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
)


def parse_dotenv(text: str) -> Dict[str, str]:
    """Parse a dotenv-style string into a flat key→value map (last wins)."""
    result: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def load_dotenv_file(path: Path | str) -> Dict[str, str]:
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f".env file not found: {path}")
    return parse_dotenv(path.read_text(encoding="utf-8", errors="replace"))


def _engine_from_scheme(scheme: str) -> Optional[str]:
    scheme = (scheme or "").lower().split("+")[0]
    return _SCHEME_TO_TYPE.get(scheme)


def parse_database_url(url: str) -> Optional[Dict[str, Any]]:
    """Parse a SQLAlchemy/Prisma-style database URL into connection fields."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip().strip("'\"")
    if "://" not in url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    engine = _engine_from_scheme(parsed.scheme)
    if not engine:
        return None

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password is not None else None
    host = parsed.hostname
    port = parsed.port
    if port is None:
        port = _DEFAULT_PORTS.get(engine)

    database = (parsed.path or "").lstrip("/") or None
    if database and "?" in database:
        database = database.split("?", 1)[0]
    if engine == "sqlite":
        database = parsed.path or database
        host = None
        port = None

    query = parse_qs(parsed.query or "")
    sslmode = None
    for key in ("sslmode", "ssl", "ssl-mode"):
        if key in query and query[key]:
            sslmode = query[key][0]
            break
    # Supabase / Prisma often encode ssl via query
    if sslmode is None and "supabase" in (host or "").lower():
        sslmode = "require"
    if sslmode in ("true", "1", "yes"):
        sslmode = "require"

    extra: Dict[str, Any] = {"import_source": "env_url"}
    if sslmode:
        extra["sslmode"] = sslmode
    if "pgbouncer" in (parsed.query or "").lower():
        extra["pgbouncer"] = True

    return {
        "type": engine,
        "host": host,
        "port": int(port) if port else None,
        "database": database,
        "username": username,
        "password": password,
        "connection_string": None,
        "extra": extra,
    }


def _discrete_db_from_env(env: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Build a profile from discrete DB_* / POSTGRES_* / MYSQL_* keys."""
    engine_hint = (
        env.get("DB_CONNECTION")
        or env.get("DB_TYPE")
        or env.get("DATABASE_TYPE")
        or ""
    ).lower()

    if engine_hint in ("pgsql", "postgres", "postgresql"):
        engine = "postgresql"
        prefixes = ["DB_", "POSTGRES_", "PG_"]
    elif engine_hint in ("mysql", "mariadb"):
        engine = "mysql"
        prefixes = ["DB_", "MYSQL_", "MARIADB_"]
    elif any(k.startswith("POSTGRES_") or k.startswith("PG_") for k in env):
        engine = "postgresql"
        prefixes = ["POSTGRES_", "PG_", "DB_"]
    elif any(k.startswith("MYSQL_") or k.startswith("MARIADB_") for k in env):
        engine = "mysql"
        prefixes = ["MYSQL_", "MARIADB_", "DB_"]
    elif env.get("DB_HOST") or env.get("DB_DATABASE") or env.get("DB_USERNAME"):
        engine = "mysql" if engine_hint in ("mysql", "mariadb") else "postgresql"
        prefixes = ["DB_"]
    else:
        return None

    def first(suffixes: Tuple[str, ...]) -> Optional[str]:
        for prefix in prefixes:
            for suffix in suffixes:
                key = f"{prefix}{suffix}"
                if env.get(key):
                    return env[key]
        return None

    host = first(("HOST", "HOSTNAME", "SERVER"))
    database = first(("DATABASE", "DB", "NAME"))
    username = first(("USERNAME", "USER", "UID"))
    password = first(("PASSWORD", "PASS", "PWD"))
    port_raw = first(("PORT",))
    if not host and not database:
        return None

    port: Optional[int] = None
    if port_raw:
        try:
            port = int(port_raw)
        except ValueError:
            port = _DEFAULT_PORTS.get(engine)
    else:
        port = _DEFAULT_PORTS.get(engine)

    return {
        "type": engine,
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
        "connection_string": None,
        "extra": {"import_source": "env_discrete"},
    }


def _name_for(key: str, fields: Dict[str, Any], source_label: str) -> str:
    host = fields.get("host") or "local"
    db = fields.get("database") or "db"
    label = key.replace("_", " ").title() if key else "Database"
    base = f"{source_label} — {label}" if source_label else label
    return f"{base} ({host}/{db})"


def import_env_file(
    path: Path | str,
    *,
    name_prefix: Optional[str] = None,
    prefer_direct: bool = True,
) -> List[Dict[str, Any]]:
    """Parse a ``.env`` file and return connection profile dicts.

    Returns one profile per distinct URL / discrete config found. Prefers
    ``DIRECT_URL`` / unpooled URLs when ``prefer_direct`` is True (listed first).
    """
    path = Path(path).expanduser().resolve()
    env = load_dotenv_file(path)
    source_label = name_prefix or path.parent.name or path.stem

    profiles: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    url_keys = list(_URL_KEYS_ALL)
    if prefer_direct:
        # Already ordered with DIRECT / UNPOOLED first
        pass
    else:
        url_keys = ["DATABASE_URL"] + [k for k in url_keys if k != "DATABASE_URL"]

    for key in url_keys:
        raw = env.get(key)
        if not raw:
            continue
        fields = parse_database_url(raw)
        if not fields:
            continue
        sig = (
            fields.get("type"),
            fields.get("host"),
            fields.get("port"),
            fields.get("database"),
            fields.get("username"),
        )
        if sig in seen:
            continue
        seen.add(sig)
        extra = dict(fields.get("extra") or {})
        extra["import_source"] = "env_file"
        extra["import_path"] = str(path)
        extra["env_key"] = key
        # Supabase project ref from host if present
        host = fields.get("host") or ""
        if "supabase" in host:
            extra["platform"] = "supabase"
        profile = {
            "id": str(uuid.uuid4()),
            "name": _name_for(key, fields, source_label),
            "type": fields["type"],
            "host": fields.get("host"),
            "port": fields.get("port"),
            "database": fields.get("database"),
            "username": fields.get("username"),
            "password": fields.get("password"),
            "connection_string": None,
            "ssh_config": None,
            "extra": extra,
        }
        profiles.append(profile)

    discrete = _discrete_db_from_env(env)
    if discrete:
        sig = (
            discrete.get("type"),
            discrete.get("host"),
            discrete.get("port"),
            discrete.get("database"),
            discrete.get("username"),
        )
        if sig not in seen:
            seen.add(sig)
            extra = dict(discrete.get("extra") or {})
            extra["import_source"] = "env_file"
            extra["import_path"] = str(path)
            profiles.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": _name_for("DB", discrete, source_label),
                    "type": discrete["type"],
                    "host": discrete.get("host"),
                    "port": discrete.get("port"),
                    "database": discrete.get("database"),
                    "username": discrete.get("username"),
                    "password": discrete.get("password"),
                    "connection_string": None,
                    "ssh_config": None,
                    "extra": extra,
                }
            )

    # Annotate SUPABASE_URL project (metadata only — not a DB connection)
    supabase_url = env.get("SUPABASE_URL")
    if supabase_url and profiles:
        for p in profiles:
            extra = p.setdefault("extra", {})
            if extra.get("platform") == "supabase" or "supabase" in (
                p.get("host") or ""
            ):
                extra["supabase_url"] = supabase_url.rstrip("/")

    return profiles
