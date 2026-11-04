"""Last window size in SecureStore, and tray Sign out via the RBAC session."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from db_storage_manager.gui.main_window import (  # noqa: E402
    saved_window_size,
    settings_with_window_size,
)
from db_storage_manager.security.auth import (  # noqa: E402
    get_auth_manager,
    reset_auth_manager,
)
from db_storage_manager.security.bootstrap import bootstrap_admin  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_saved_window_size_ignores_position_and_bad_values():
    assert saved_window_size({}) is None
    assert (
        saved_window_size({"window": {"width": 100, "height": 100}}) is None
    )
    assert saved_window_size({"window": {"width": "no", "height": 900}}) is None
    assert saved_window_size(
        {"window": {"width": 1400, "height": 900, "x": 40, "y": -8}}
    ) == (1400, 900)
    assert (
        saved_window_size({"window": {"width": 20000, "height": 900}}) is None
    )


def test_settings_with_window_size_drops_position_and_skips_same_size():
    base = {"theme": "dark", "window": {"width": 1400, "height": 900, "x": 3}}
    updated = settings_with_window_size(base, 1400, 900)
    assert updated is not None
    assert updated["theme"] == "dark"
    assert updated["window"] == {"width": 1400, "height": 900}
    assert settings_with_window_size(updated, 1400, 900) is None
    assert settings_with_window_size(base, 100, 900) is None


def test_close_saves_size_and_next_window_restores_it(
    app, isolated_secure_store
):
    store, _ = isolated_secure_store
    reset_auth_manager()
    from db_storage_manager.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    window.resize(1280, 900)
    app.processEvents()
    assert window.width() == 1280
    assert window.height() == 900
    window._quitting = True
    window.close()
    app.processEvents()
    assert store.get_settings()["window"] == {"width": 1280, "height": 900}

    again = MainWindow()
    again.show()
    app.processEvents()
    assert again.width() == 1280
    assert again.height() == 900
    again._quitting = True
    again.close()
    app.processEvents()


def test_tray_sign_out_follows_the_rbac_session(app):
    """The menu item is hidden until a session exists, then emits sign-out."""
    from PyQt6.QtWidgets import QWidget

    from db_storage_manager.gui.tray import AppTray

    window = QWidget()
    window.show()
    allowed = {"on": False}
    tray = AppTray(window, can_sign_out=lambda: allowed["on"])
    assert tray.sign_out_action.text() == "Sign out"
    assert not tray.sign_out_action.isVisible()
    allowed["on"] = True
    tray.refresh_status()
    assert tray.sign_out_action.isVisible()
    seen = []
    tray.sign_out_requested.connect(lambda: seen.append("out"))
    tray.sign_out_action.trigger()
    app.processEvents()
    assert seen == ["out"]
    window.close()
    app.processEvents()


def test_tray_sign_out_reuses_logout_and_login(
    app, isolated_secure_store, monkeypatch
):
    store, _ = isolated_secure_store
    reset_auth_manager()
    bootstrap_admin("admin", "password123", store=store)
    auth = get_auth_manager()
    auth.reload()
    assert auth.authenticate("admin", "password123") is not None

    from db_storage_manager.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    assert window._tray_can_sign_out()

    class _Accepted:
        def __init__(self, parent=None):
            self.parent = parent

        def exec(self):
            get_auth_manager().authenticate("admin", "password123")
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "db_storage_manager.gui.login.LoginDialog", _Accepted
    )
    window._sign_out()
    app.processEvents()
    assert get_auth_manager().current_user is not None
    assert get_auth_manager().current_user.username == "admin"
    assert window.isVisible()
    window._quitting = True
    window.close()
    app.processEvents()
    reset_auth_manager()


def test_tray_sign_out_quits_when_login_is_cancelled(
    app, isolated_secure_store, monkeypatch
):
    store, _ = isolated_secure_store
    reset_auth_manager()
    bootstrap_admin("admin", "password123", store=store)
    auth = get_auth_manager()
    auth.reload()
    auth.authenticate("admin", "password123")

    from db_storage_manager.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()

    class _Rejected:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "db_storage_manager.gui.login.LoginDialog", _Rejected
    )
    window._sign_out()
    app.processEvents()
    assert get_auth_manager().current_user is None
    assert window._quitting is True
    reset_auth_manager()
