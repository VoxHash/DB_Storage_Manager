"""SecureStore encrypt/decrypt round-trips and failure handling (real Fernet)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from db_storage_manager.config import DEFAULT_SETTINGS


def test_master_key_created_with_restrictive_mode(isolated_secure_store):
    store, data_dir = isolated_secure_store
    key_path = data_dir / ".master-key"
    assert key_path.exists()
    assert store._master_key is not None
    assert len(store._master_key) > 0
    # Unix: 0o600; Windows may not support the same mode bits
    import os

    if os.name != "nt":
        assert oct(key_path.stat().st_mode & 0o777) == "0o600"


def test_connections_encrypt_decrypt_roundtrip(isolated_secure_store):
    store, data_dir = isolated_secure_store
    profiles = [
        {
            "id": "c1",
            "name": "local-sqlite",
            "type": "sqlite",
            "database": "/tmp/demo.db",
            "password": "s3cret-value",
        }
    ]
    store.save_connections(profiles)

    enc_file = data_dir / "connections.enc"
    assert enc_file.exists()
    raw = enc_file.read_text(encoding="utf-8")
    assert "s3cret-value" not in raw
    assert "local-sqlite" not in raw

    loaded = store.get_connections()
    assert loaded == profiles

    # Second SecureStore instance with same key file reloads ciphertext
    from db_storage_manager.security.store import SecureStore

    store2 = SecureStore()
    assert store2.get_connections() == profiles


def test_settings_and_ssh_keys_roundtrip(isolated_secure_store):
    store, _ = isolated_secure_store
    settings = {**DEFAULT_SETTINGS, "theme": "light", "safe_mode": False}
    store.set_settings(settings)
    assert store.get_settings()["theme"] == "light"
    assert store.get_settings()["safe_mode"] is False

    keys = [{"id": "k1", "name": "lab", "private_key": "BEGIN-SECRET"}]
    store.save_ssh_keys(keys)
    assert store.get_ssh_keys() == keys


def test_encrypt_decrypt_primitives(isolated_secure_store):
    store, _ = isolated_secure_store
    payload = {"hello": "world", "n": 42}
    token = store._encrypt(payload)
    assert isinstance(token, str)
    assert store._decrypt(token) == payload


def test_decrypt_fails_on_tampered_ciphertext(isolated_secure_store):
    store, _ = isolated_secure_store
    token = store._encrypt({"ok": True})
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises((InvalidToken, Exception)):
        store._decrypt(tampered)


def test_decrypt_fails_with_wrong_master_key(isolated_secure_store, monkeypatch):
    store, data_dir = isolated_secure_store
    store.save_connections([{"id": "keep", "name": "x"}])

    import db_storage_manager.security.store as store_mod
    from db_storage_manager.security.store import SecureStore

    # Overwrite master key with a different Fernet key; ciphertext must not decrypt
    wrong_key = Fernet.generate_key()
    (data_dir / ".master-key").write_bytes(wrong_key)
    monkeypatch.setattr(store_mod, "MASTER_KEY_FILE", data_dir / ".master-key")

    broken = SecureStore()
    # Public API swallows decrypt errors and returns empty list
    assert broken.get_connections() == []


def test_corrupt_settings_file_returns_defaults(isolated_secure_store):
    store, data_dir = isolated_secure_store
    store.set_settings({**DEFAULT_SETTINGS, "theme": "dracula"})
    (data_dir / "settings.enc").write_text("not-valid-fernet-payload", encoding="utf-8")
    restored = store.get_settings()
    assert restored == DEFAULT_SETTINGS


def test_corrupt_connections_file_returns_empty(isolated_secure_store):
    store, data_dir = isolated_secure_store
    store.save_connections([{"id": "gone"}])
    (data_dir / "connections.enc").write_text(
        base64.b64encode(b"garbage-not-fernet").decode("utf-8"),
        encoding="utf-8",
    )
    assert store.get_connections() == []


def test_missing_files_return_defaults(isolated_secure_store):
    store, data_dir = isolated_secure_store
    assert not (data_dir / "connections.enc").exists()
    assert store.get_connections() == []
    assert store.get_ssh_keys() == []
    assert store.get_settings() == DEFAULT_SETTINGS
