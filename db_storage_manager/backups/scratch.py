"""Create an empty scratch database for a restore rehearsal.

The production database named by the operator's connection is never opened
for writing. SQLite rehearsals land in a new file beside the original.
PostgreSQL and MySQL rehearsals ``CREATE DATABASE`` a new name on the same
server and leave every other database alone.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..db.base import ConnectionConfig

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class ScratchError(RuntimeError):
    """The scratch database could not be created. Production was not modified."""


def scratch_identifier(source_name: str, *, now: Optional[datetime] = None) -> str:
    """A safe database name: ``dsm_scratch_<slug>_<utc stamp>``."""
    moment = now or datetime.now(timezone.utc)
    slug = re.sub(r"[^a-z0-9]+", "_", (source_name or "db").lower()).strip("_")
    slug = (slug[:24] or "db")
    name = f"dsm_scratch_{slug}_{moment.strftime('%Y%m%d%H%M%S')}"
    if not _IDENT.match(name):
        raise ScratchError(f"refusing unsafe scratch name {name!r}")
    return name


def quote_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ScratchError(f"refusing unsafe identifier {name!r}")
    return name


def sqlite_scratch_path(database: str, *, directory: Optional[Path] = None) -> Path:
    source = Path(database)
    parent = Path(directory) if directory is not None else source.parent
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = source.suffix or ".db"
    dest = parent / f"{source.stem}.scratch-{stamp}{suffix}"
    if dest.exists():
        raise ScratchError(f"scratch file already exists: {dest}")
    return dest


def provision_server_database(config: ConnectionConfig, name: str) -> None:
    """``CREATE DATABASE`` ``name`` on the server ``config`` already uses.

    Connects to the maintenance database (``postgres`` / no schema), not to
    the production database.
    """
    safe = quote_ident(name)
    family = str(config.type or "").strip().lower()
    if family in {"postgresql", "postgres", "supabase"}:
        import psycopg2

        from ..cloud.connect_auth import resolve_password_and_ssl

        password, ssl_kwargs = resolve_password_and_ssl(config)
        kwargs = {
            "host": config.host or "localhost",
            "port": config.port or 5432,
            "dbname": "postgres",
            "user": config.username,
            "password": password,
        }
        if ssl_kwargs.get("sslmode"):
            kwargs["sslmode"] = ssl_kwargs["sslmode"]
        if ssl_kwargs.get("sslrootcert"):
            kwargs["sslrootcert"] = ssl_kwargs["sslrootcert"]
        conn = psycopg2.connect(**kwargs)
        try:
            conn.autocommit = True
            conn.cursor().execute(f'CREATE DATABASE "{safe}"')
        finally:
            conn.close()
        return
    if family in {"mysql", "mariadb"}:
        import pymysql

        conn = pymysql.connect(
            host=config.host or "localhost",
            port=int(config.port or 3306),
            user=config.username,
            password=config.password or "",
            autocommit=True,
            charset="utf8mb4",
        )
        try:
            conn.cursor().execute(
                f"CREATE DATABASE `{safe}` CHARACTER SET utf8mb4"
            )
        finally:
            conn.close()
        return
    raise ScratchError(
        f"Scratch restore is available for SQLite, PostgreSQL and MySQL. "
        f"This connection is {config.type}."
    )
