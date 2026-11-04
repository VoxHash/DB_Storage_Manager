"""Shared pytest fixtures for DB Storage Manager tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep RBAC password hashing fast in the test suite (production default is 390k).
os.environ.setdefault("DSM_PBKDF2_ITERATIONS", "12000")


@pytest.fixture(autouse=True)
def _isolated_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Never read or write the developer's real language preference."""
    import db_storage_manager.i18n.manager as i18n_mod

    monkeypatch.setattr(i18n_mod, "LANGUAGE_FILE", tmp_path / "language.json")
    monkeypatch.setattr(i18n_mod, "_i18n_manager", None)
    yield
    i18n_mod._i18n_manager = None


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
    monkeypatch.setattr(
        store_mod,
        "SCHEDULED_BACKUP_SECRETS_FILE",
        data_dir / "scheduled-backup-secrets.enc",
    )
    monkeypatch.setattr(
        store_mod, "PLUGIN_LICENSES_FILE", data_dir / "plugin-licenses.enc"
    )

    import db_storage_manager.config as config_mod

    monkeypatch.setattr(config_mod, "USERS_FILE", data_dir / "users.enc")

    from db_storage_manager.security.auth import reset_auth_manager

    reset_auth_manager()

    return SecureStore(), data_dir


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Close pooled SQL engine threads so the interpreter can exit promptly."""
    try:
        from db_storage_manager.db.pool import close_sql_engine_pool_blocking

        close_sql_engine_pool_blocking()
    except Exception:
        pass
