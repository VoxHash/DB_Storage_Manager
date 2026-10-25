"""Multi-user RBAC: password hashing, SecureStore users, enforcement, Qt smoke."""

from __future__ import annotations

import base64
import os
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from db_storage_manager.api.server import create_server
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
    get_auth_manager,
    hash_password,
    reset_auth_manager,
    verify_password,
)
from db_storage_manager.security.bootstrap import bootstrap_admin


def test_password_hash_roundtrip_and_reject():
    stored = hash_password("correct-horse-battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("correct-horse-battery", "garbage")


def test_open_mode_allows_all_when_no_users(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    assert not auth.is_rbac_active()
    assert auth.has_permission("connections:write")
    assert auth.has_permission("users:manage")
    auth.require("plugins:manage")  # must not raise


def test_bootstrap_admin_persists_and_requires_login(isolated_secure_store):
    store, data_dir = isolated_secure_store
    name = bootstrap_admin(
        "admin", "password123", email="a@local", store=store
    )
    assert name == "admin"
    assert (data_dir / "users.enc").is_file()

    reset_auth_manager()
    auth = AuthenticationManager(store=store)
    assert auth.is_rbac_active()
    assert auth.current_user is None
    assert not auth.has_permission("connections:write")
    with pytest.raises(PermissionDenied):
        auth.require("connections:write")

    user = auth.authenticate("admin", "password123")
    assert user is not None
    assert user.role == UserRole.ADMIN
    assert auth.has_permission("users:manage")
    assert auth.has_permission("plugins:manage")


def test_viewer_denied_sensitive_actions(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user(
        "viewer1", "password123", role=UserRole.VIEWER, email="v@local"
    )
    auth.logout()
    assert auth.authenticate("viewer1", "password123") is not None
    assert auth.has_permission("connections:read")
    assert auth.has_permission("backups:read")
    assert not auth.has_permission("connections:write")
    assert not auth.has_permission("connections:delete")
    assert not auth.has_permission("backups:restore")
    assert not auth.has_permission("settings:write")
    assert not auth.has_permission("plugins:manage")
    assert not auth.has_permission("users:manage")
    with pytest.raises(PermissionDenied) as exc:
        auth.require("plugins:manage")
    assert exc.value.permission == "plugins:manage"


def test_wrong_password_rejected(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    assert auth.authenticate("admin", "nope-nope") is None
    assert auth.current_user is None


def test_cannot_delete_last_admin(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    with pytest.raises(ValueError, match="last admin"):
        auth.delete_user("admin")


def test_mfa_required_when_enabled(isolated_secure_store):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    secret = auth.enable_mfa("admin")
    auth.logout()
    assert auth.authenticate("admin", "password123") is None
    import pyotp

    token = pyotp.TOTP(secret).now()
    assert auth.authenticate("admin", "password123", mfa_token=token)


def test_api_rbac_basic_and_forbidden(isolated_secure_store, tmp_path):
    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("viewer1", "password123", role=UserRole.VIEWER)
    auth.logout()
    reset_auth_manager()
    # Point singleton at same store for the HTTP handler
    from db_storage_manager.security import auth as auth_mod

    auth_mod._auth_manager = AuthenticationManager(store=store)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    server = create_server(
        "127.0.0.1", 0, api_token="machine-token", backup_dir=backup_dir
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Unauthenticated → 401 when RBAC active
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/v1/connections")
        assert conn.getresponse().status == 401
        conn.close()

        # Viewer Basic: can read connections, cannot dry-run
        basic = base64.b64encode(b"viewer1:password123").decode("ascii")
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/api/v1/connections",
            headers={"Authorization": f"Basic {basic}"},
        )
        assert conn.getresponse().status == 200
        conn.close()

        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "POST",
            "/api/v1/backups/dry-run",
            body=b"{}",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        assert resp.status == 403
        body = resp.read().decode("utf-8")
        assert "backups:restore" in body
        conn.close()

        # Machine Bearer → system admin
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/api/v1/connections",
            headers={"Authorization": "Bearer machine-token"},
        )
        assert conn.getresponse().status == 200
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        reset_auth_manager()


def test_users_admin_and_login_offscreen_smoke(isolated_secure_store, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    store, _ = isolated_secure_store
    reset_auth_manager()
    from db_storage_manager.security import auth as auth_mod

    auth_mod._auth_manager = AuthenticationManager(store=store)

    from PyQt6.QtWidgets import QApplication, QDialog

    app = QApplication.instance() or QApplication([])

    from db_storage_manager.gui.users import UsersAdminWidget
    from db_storage_manager.gui.login import LoginDialog
    from db_storage_manager.gui.settings import SettingsWidget

    widget = UsersAdminWidget()
    widget.show()
    assert not get_auth_manager().is_rbac_active()
    assert widget.bootstrap_btn.isEnabled()

    bootstrap_admin("admin", "password123", store=store)
    get_auth_manager().reload()
    get_auth_manager().authenticate("admin", "password123")
    widget.refresh()
    assert get_auth_manager().is_rbac_active()
    assert widget.table.rowCount() == 1
    assert widget.add_btn.isEnabled()

    settings = SettingsWidget()
    settings.show()
    assert settings.users_admin.table.rowCount() == 1

    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    get_auth_manager().logout()
    dlg = LoginDialog()
    dlg.username_edit.setText("admin")
    dlg.password_edit.setText("password123")
    dlg._try_login()
    assert get_auth_manager().current_user is not None
    assert get_auth_manager().current_user.username == "admin"
    assert dlg.result() == int(QDialog.DialogCode.Accepted)

    get_auth_manager().logout()
    dlg2 = LoginDialog()
    dlg2.username_edit.setText("admin")
    dlg2.password_edit.setText("bad-bad-bad")
    dlg2._try_login()
    assert get_auth_manager().current_user is None

    widget.close()
    settings.close()
