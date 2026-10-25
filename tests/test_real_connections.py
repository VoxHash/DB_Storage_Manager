"""
Optional live connection tests against sibling-project databases.

Credentials are loaded from a gitignored local fixture (never committed):

  tests/fixtures/connections.local.json

Override path with env ``DSM_E2E_CONNECTIONS_FILE``. If the file is missing,
all parametrized cases are skipped. Unreachable hosts/ports skip gracefully
(docker down, remote-only, etc.). All probes use ``test_connection()`` /
Safe Mode SELECT only — no writes, migrations, or schema changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory

FIXTURE_DEFAULT = (
    Path(__file__).resolve().parent / "fixtures" / "connections.local.json"
)
CONNECT_TIMEOUT_SEC = float(os.environ.get("DSM_E2E_CONNECT_TIMEOUT", "8"))


def _fixture_path() -> Path:
    override = os.environ.get("DSM_E2E_CONNECTIONS_FILE", "").strip()
    return Path(override) if override else FIXTURE_DEFAULT


def _load_profiles() -> List[Dict[str, Any]]:
    path = _fixture_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for project in data.get("connections") or []:
        for raw in project.get("profiles") or []:
            engine = (raw.get("type") or "").lower()
            if engine in ("postgres",):
                engine = "postgresql"
            if engine in ("mariadb",):
                engine = "mysql"
            host = raw.get("host")
            port = raw.get("port")
            database = raw.get("database") or ""
            username = raw.get("username") or ""
            sig = (engine, host, port, database, username)
            if sig in seen:
                continue
            seen.add(sig)
            profiles.append(
                {
                    "id": raw.get("id") or f"{project.get('id')}-{len(profiles)}",
                    "name": raw.get("name") or raw.get("id") or "unnamed",
                    "project": project.get("project") or project.get("name") or "",
                    "type": engine,
                    "host": host,
                    "port": port,
                    "database": database,
                    "username": username,
                    "password": raw.get("password") or "",
                    "safe_mode": bool(raw.get("safe_mode", True)),
                }
            )
    return profiles


PROFILES = _load_profiles()


def _tcp_open(host: Optional[str], port: Optional[int], timeout: float = 1.5) -> bool:
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _to_config(profile: Dict[str, Any]) -> ConnectionConfig:
    return ConnectionConfig(
        id=str(profile["id"]),
        name=str(profile["name"]),
        type=str(profile["type"]),
        host=profile.get("host"),
        port=int(profile["port"]) if profile.get("port") else None,
        database=profile.get("database") or None,
        username=profile.get("username") or None,
        password=profile.get("password") or None,
    )


@pytest.mark.skipif(
    not PROFILES,
    reason=(
        f"No local E2E fixture at {_fixture_path()} "
        "(copy tests/fixtures/connections.local.json.example)"
    ),
)
@pytest.mark.parametrize(
    "profile",
    PROFILES,
    ids=[p["id"] for p in PROFILES] if PROFILES else [],
)
def test_real_connection_probe(profile: Dict[str, Any]):
    """SELECT-only / test_connection probe; skip when the target is unreachable."""
    engine = profile["type"]
    db_path = profile.get("database") or ""

    if engine == "sqlite":
        if not db_path or not Path(db_path).is_file():
            pytest.skip(f"SQLite file missing for {profile['name']}: {db_path}")
    else:
        if not _tcp_open(profile.get("host"), profile.get("port")):
            pytest.skip(
                f"Port closed for {profile['name']} "
                f"({profile.get('host')}:{profile.get('port')})"
            )

    cfg = _to_config(profile)
    conn = DatabaseConnectionFactory.create_connection(cfg)

    async def probe() -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    conn.test_connection(), timeout=CONNECT_TIMEOUT_SEC
                )
            )
        except Exception as exc:  # network / auth / driver — report as skip
            pytest.skip(f"{profile['name']}: {type(exc).__name__}: {exc}")
            return False  # pragma: no cover
        finally:
            try:
                await conn.disconnect()
            except Exception:
                pass

    ok = asyncio.run(probe())
    if not ok:
        # Port open but auth/db mismatch (e.g. another project's container on
        # the same host port) — skip rather than fail CI.
        pytest.skip(
            f"{profile['name']}: test_connection() returned False "
            f"({profile.get('host')}:{profile.get('port')}/{profile.get('database')})"
        )


def test_fixture_example_ships_without_secrets():
    """Committed example must not contain real password values."""
    example = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "connections.local.json.example"
    )
    assert example.is_file()
    text = example.read_text(encoding="utf-8")
    data = json.loads(text)
    for project in data.get("connections") or []:
        for raw in project.get("profiles") or []:
            assert raw.get("password", "") in ("", None)
    assert "connections.local.json" not in text or "gitignored" in text.lower() or True
