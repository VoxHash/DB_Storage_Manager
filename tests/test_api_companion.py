"""REST + Web UI companion (real HTTP server, SecureStore, local backups)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from db_storage_manager.api.sanitize import sanitize_connection, sanitize_connections
from db_storage_manager.api.server import create_server
from db_storage_manager.api import service
from db_storage_manager.backups.base import BackupOptions
from db_storage_manager.backups.local import LocalBackupAdapter
from db_storage_manager.security.store import SecureStore


def _sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO t(name) VALUES ('x')")
        conn.commit()
    finally:
        conn.close()


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


@pytest.fixture
def companion(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    server = create_server("127.0.0.1", 0, api_token=None, backup_dir=backup_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    yield {"server": server, "base": base, "backup_dir": backup_dir}
    server.shutdown()
    server.server_close()


@pytest.fixture
def companion_auth(tmp_path: Path):
    backup_dir = tmp_path / "backups-auth"
    backup_dir.mkdir()
    server = create_server(
        "127.0.0.1", 0, api_token="secret-token", backup_dir=backup_dir
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    yield {"server": server, "base": base, "backup_dir": backup_dir, "token": "secret-token"}
    server.shutdown()
    server.server_close()


def test_sanitize_strips_passwords():
    raw = {
        "id": "1",
        "name": "prod",
        "password": "hunter2",
        "ssh_config": {"enabled": True, "ssh_password": "bastion", "ssh_host": "b"},
    }
    clean = sanitize_connection(raw)
    assert clean["password"] == "***"
    assert clean["ssh_config"]["ssh_password"] == "***"
    assert clean["ssh_config"]["ssh_host"] == "b"
    assert sanitize_connections([raw])[0]["name"] == "prod"


def test_health_and_web_ui(companion):
    status, health = _http_json(f"{companion['base']}/api/v1/health")
    assert status == 200
    assert health["ok"] is True
    assert health["status"] == "healthy"

    req = urllib.request.Request(f"{companion['base']}/")
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "DB Storage Manager" in html
        assert "Companion" in html

    css_req = urllib.request.Request(f"{companion['base']}/static/style.css")
    with urllib.request.urlopen(css_req, timeout=5) as resp:
        assert resp.status == 200
        assert b"--accent" in resp.read()


def test_info_and_connections(companion, isolated_secure_store):
    store = SecureStore()
    store.save_connections(
        [
            {
                "id": "c1",
                "name": "local-sqlite",
                "type": "sqlite",
                "password": "should-not-leak",
                "database": ":memory:",
            }
        ]
    )
    status, info = _http_json(f"{companion['base']}/api/v1/info")
    assert status == 200
    assert info["desktop_primary"] is True
    assert "native" in info

    status, payload = _http_json(f"{companion['base']}/api/v1/connections")
    assert status == 200
    assert payload["ok"] is True
    assert len(payload["connections"]) == 1
    assert payload["connections"][0]["password"] == "***"
    assert payload["connections"][0]["name"] == "local-sqlite"


def test_backups_verify_and_dry_run(companion, tmp_path: Path):
    source = tmp_path / "src.db"
    _sqlite_db(source)
    adapter = LocalBackupAdapter(base_path=companion["backup_dir"])
    info = asyncio.run(
        adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="api-demo",
                databaseType="sqlite",
                backupPath=str(source),
            )
        )
    )

    status, listed = _http_json(f"{companion['base']}/api/v1/backups")
    assert status == 200
    assert listed["ok"] is True
    assert len(listed["backups"]) == 1
    assert listed["backups"][0]["id"] == info.id

    status, verified = _http_json(
        f"{companion['base']}/api/v1/backups/{info.id}/verify",
        method="POST",
        body={},
    )
    assert status == 200
    assert verified["ok"] is True
    assert verified["status"] == "pass"

    status, dry = _http_json(
        f"{companion['base']}/api/v1/backups/{info.id}/dry-run",
        method="POST",
        body={},
    )
    assert status == 200
    assert dry["ok"] is True
    assert dry["integrity"] == "ok"
    # Live DB untouched
    conn = sqlite3.connect(str(source))
    try:
        count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_bearer_auth_required(companion_auth):
    base = companion_auth["base"]
    token = companion_auth["token"]

    status, health = _http_json(f"{base}/api/v1/health")
    assert status == 200
    assert health["ok"] is True

    status, denied = _http_json(f"{base}/api/v1/connections")
    assert status == 401
    assert denied["ok"] is False

    status, ok = _http_json(f"{base}/api/v1/connections", token=token)
    assert status == 200
    assert ok["ok"] is True


def test_service_health_shape():
    payload = service.health_payload()
    assert payload["ok"] is True
    assert "version" in payload
