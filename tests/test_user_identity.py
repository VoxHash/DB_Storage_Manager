"""Admin can change a user's username and email. The record stays in SecureStore."""

from __future__ import annotations

import pytest

from db_storage_manager import config
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
)


def test_rename_and_email_round_trip_securestore(isolated_secure_store, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123", email="admin@localhost")
    auth.authenticate("admin", "password123")
    auth.create_user("ada", "password123", email="old@example.com", role=UserRole.USER)
    secret = auth.begin_mfa("ada")

    updated = auth.update_user_identity(
        "ada", new_username="ada.lovelace", email="ada@example.com"
    )
    assert updated.username == "ada.lovelace"
    assert updated.email == "ada@example.com"
    assert updated.mfa_pending_secret == secret
    assert updated.mfa_enabled is False
    assert auth.get_user("ada") is None

    reloaded = AuthenticationManager(store=store)
    again = reloaded.get_user("ada.lovelace")
    assert again is not None
    assert again.email == "ada@example.com"
    assert again.mfa_pending_secret == secret
    assert again.password_hash == updated.password_hash
    raw = config.USERS_FILE.read_bytes()
    assert b"ada@example.com" not in raw
    assert b"password123" not in raw


def test_identity_rejects_bad_email_duplicate_and_non_admin(
    isolated_secure_store, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123", email="admin@localhost")
    auth.authenticate("admin", "password123")
    auth.create_user("ada", "password123", email="ada@example.com")
    auth.create_user("viewer", "password123", email="view@example.com", role=UserRole.VIEWER)

    with pytest.raises(ValueError, match="email"):
        auth.update_user_identity("ada", new_username="ada", email="not-an-email")
    with pytest.raises(ValueError, match="already in use"):
        auth.update_user_identity("ada", new_username="admin", email="ada@example.com")
    with pytest.raises(ValueError, match="Username"):
        auth.update_user_identity("ada", new_username="bad name", email="ada@example.com")

    auth.logout()
    auth.authenticate("viewer", "password123")
    with pytest.raises(PermissionDenied):
        auth.update_user_identity(
            "viewer", new_username="viewer", email="view2@example.com"
        )
    assert auth.get_user("ada").email == "ada@example.com"
