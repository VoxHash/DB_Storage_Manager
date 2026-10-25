"""Offscreen smoke for modern desktop shell (sidebar + theme + login)."""

from __future__ import annotations

import os

import pytest

from db_storage_manager.security.auth import (
    AuthenticationManager,
    get_auth_manager,
    reset_auth_manager,
)
from db_storage_manager.security.bootstrap import bootstrap_admin
from db_storage_manager.themes.themes import THEMES, DEFAULT_THEME
from db_storage_manager.gui.utils import build_app_stylesheet


def test_theme_tokens_include_shell_keys():
    assert DEFAULT_THEME == "dark"
    for key, theme in THEMES.items():
        colors = theme["colors"]
        for token in (
            "background",
            "surface",
            "primary",
            "text",
            "text_secondary",
            "border",
            "sidebar_bg",
            "sidebar_hover",
            "sidebar_active",
            "content_bg",
            "on_primary",
        ):
            assert token in colors, f"{key} missing {token}"
        sheet = build_app_stylesheet(colors)
        assert "NavSidebar" in sheet
        assert colors["primary"] in sheet


def test_main_window_shell_offscreen(isolated_secure_store, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    store, data_dir = isolated_secure_store
    reset_auth_manager()

    import db_storage_manager.themes.manager as theme_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.themes.manager import get_theme_manager

    get_theme_manager().set_theme("dark")

    window = MainWindow()
    window.show()

    assert window.sidebar is not None
    assert window.sidebar.width() == 220
    assert window.tab_widget.count() == 7
    assert not window.tab_widget.tabBar().isVisible()

    window.sidebar.set_current_index(2)
    window._on_sidebar_navigated(2)
    assert window.tab_widget.currentIndex() == 2

    window.tab_widget.setCurrentIndex(4)
    assert window.sidebar._buttons[4].isChecked()

    get_theme_manager().set_theme("light")
    window._on_theme_changed("light")
    assert "NavSidebar" in window.styleSheet()

    get_theme_manager().set_theme("dracula")
    window._on_theme_changed("dracula")

    window.close()


def test_login_dialog_shell_offscreen(isolated_secure_store, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    store, _ = isolated_secure_store
    reset_auth_manager()

    from db_storage_manager.security import auth as auth_mod

    auth_mod._auth_manager = AuthenticationManager(store=store)

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    bootstrap_admin("admin", "password123", store=store)
    get_auth_manager().reload()

    from PyQt6.QtWidgets import QFrame

    from db_storage_manager.gui.login import LoginDialog

    dlg = LoginDialog()
    card = dlg.findChild(QFrame, "LoginCard")
    assert card is not None
    assert "PrimaryButton" in dlg.styleSheet() or "LoginCard" in dlg.styleSheet()

    dlg.username_edit.setText("admin")
    dlg.password_edit.setText("password123")
    dlg._try_login()
    assert get_auth_manager().current_user is not None
    assert dlg.result() == int(QDialog.DialogCode.Accepted)
