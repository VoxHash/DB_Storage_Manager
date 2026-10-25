"""Shared pytest fixtures for DB Storage Manager tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep RBAC password hashing fast in the test suite (production default is 390k).
os.environ.setdefault("DSM_PBKDF2_ITERATIONS", "12000")


@pytest.fixture
def isolated_secure_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SecureStore using real Fernet crypto under an isolated tmp data dir."""
    import db_storage_manager.security.store as store_mod
    from db_storage_manager.security.store import SecureStore

    data_dir = tmp_path / "secure-data"
    data_dir.mkdir()

    monkeypatch.setattr(store_mod, "USER_DATA_DIR", data_dir)
    monkeypatch.setattr(store_mod, "MASTER_KEY_FILE", data_dir / ".master-key")
    monkeypatch.setattr(store_mod, "CONNECTIONS_FILE", data_dir / "connections.enc")
    monkeypatch.setattr(store_mod, "SETTINGS_FILE", data_dir / "settings.enc")
    monkeypatch.setattr(store_mod, "SSH_KEYS_FILE", data_dir / "ssh-keys.enc")
    monkeypatch.setattr(store_mod, "USERS_FILE", data_dir / "users.enc")

    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "USERS_FILE", data_dir / "users.enc")

    from db_storage_manager.security.auth import reset_auth_manager

    reset_auth_manager()

    return SecureStore(), data_dir
