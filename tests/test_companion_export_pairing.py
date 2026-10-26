"""Companion pairing tokens + sanitized credential export."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from db_storage_manager.api.server import create_server
from db_storage_manager.export.companion import (
    EXPORT_FORMAT,
    CompanionExportError,
    export_companion_bundle,
    write_companion_export,
)
from db_storage_manager.security.pairing import (
    create_pairing_token,
    hash_pairing_token,
    pairing_status,
    resolve_api_bearer_ok,
    revoke_pairing_token,
    verify_pairing_token,
)
from db_storage_manager.security.store import SecureStore


def _http_json(url: str, *, token: str | None = None):
    import urllib.error
    import urllib.request

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
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


def test_pairing_create_verify_revoke(isolated_secure_store):
    store = SecureStore()
    assert pairing_status(store)["paired"] is False
    token = create_pairing_token(store, label="test-phone")
    assert len(token) >= 32
    status = pairing_status(store)
    assert status["paired"] is True
    assert status["label"] == "test-phone"
    assert status["token_fingerprint"].startswith(hash_pairing_token(token)[:12])
    assert verify_pairing_token(token, store)
    assert not verify_pairing_token("wrong-token", store)
    ok, source = resolve_api_bearer_ok(token, env_token="")
    assert ok and source == "pairing"
    ok_env, source_env = resolve_api_bearer_ok(
        "env-secret", env_token="env-secret", store=store
    )
    assert ok_env and source_env == "env"
    assert revoke_pairing_token(store) is True
    assert pairing_status(store)["paired"] is False
    assert not verify_pairing_token(token, store)


def test_export_redacts_secrets_by_default(isolated_secure_store, tmp_path: Path):
    store = SecureStore()
    store.save_connections(
        [
            {
                "id": "1",
                "name": "prod",
                "type": "postgresql",
                "password": "hunter2",
                "host": "db.example",
            }
        ]
    )
    bundle = export_companion_bundle(store)
    assert bundle["format"] == EXPORT_FORMAT
    assert bundle["secrets_mode"] == "redacted"
    assert bundle["connections"][0]["password"] == "***"
    assert bundle["connections"][0]["host"] == "db.example"
    assert bundle["include_secrets"] is False

    with pytest.raises(CompanionExportError):
        export_companion_bundle(store, include_secrets=True, consent=False)

    secret_bundle = export_companion_bundle(
        store, include_secrets=True, consent=True
    )
    assert secret_bundle["secrets_mode"] == "plaintext_with_consent"
    assert secret_bundle["connections"][0]["password"] == "hunter2"
    assert "PLAINTEXT" in secret_bundle["warnings"][0]

    out = tmp_path / "export.json"
    write_companion_export(out, store)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["connections"][0]["password"] == "***"
    # pairing fingerprint may appear; full token hash must not be dumped as bearer
    assert "pairing_token_hash" not in json.dumps(loaded)


def test_api_accepts_pairing_bearer(isolated_secure_store, tmp_path: Path):
    store = SecureStore()
    store.save_connections(
        [{"id": "c1", "name": "local", "type": "sqlite", "password": "secret"}]
    )
    token = create_pairing_token(store)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    server = create_server("127.0.0.1", 0, api_token=None, backup_dir=backup_dir)
    assert server.pairing_configured is True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        status, _ = _http_json(f"{base}/api/v1/health")
        assert status == 200
        status, denied = _http_json(f"{base}/api/v1/connections")
        assert status == 401
        status, ok = _http_json(f"{base}/api/v1/connections", token=token)
        assert status == 200
        assert ok["connections"][0]["password"] == "***"
        status, bad = _http_json(f"{base}/api/v1/connections", token="nope")
        assert status == 401
    finally:
        server.shutdown()
        server.server_close()
