"""Offscreen smoke for modern desktop shell (sidebar + theme + login)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from db_storage_manager.security.auth import (
    AuthenticationManager,
    get_auth_manager,
    reset_auth_manager,
)
from db_storage_manager.security.bootstrap import bootstrap_admin
from db_storage_manager.themes.themes import THEMES, DEFAULT_THEME
from db_storage_manager.gui.utils import build_app_stylesheet

_NAV_SECTION_COUNT = 7
_THEME_KEYS = ("dark", "light", "dracula")  # Atmospheric / Light / Dracula
_REPO_ROOT = Path(__file__).resolve().parents[1]
_RBAC_ENV_PATH = _REPO_ROOT / ".env.rbac.local"


def _load_rbac_local_credentials() -> tuple[str, str]:
    """Load USERNAME/PASSWORD from gitignored .env.rbac.local (skip if absent)."""
    if not _RBAC_ENV_PATH.is_file():
        pytest.skip(".env.rbac.local not present on this workstation")
    values: dict[str, str] = {}
    for raw in _RBAC_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip("'\"")
    username = values.get("USERNAME", "").strip()
    password = values.get("PASSWORD", "")
    if not username or not password:
        pytest.skip(".env.rbac.local missing USERNAME or PASSWORD")
    return username, password


def test_theme_tokens_include_shell_keys():
    assert DEFAULT_THEME == "dark"
    assert THEMES["dark"]["name"] == "Atmospheric"
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
    assert window.tab_widget.count() == _NAV_SECTION_COUNT
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


def test_post_login_click_through_shell_offscreen(isolated_secure_store, monkeypatch):
    """Sign-in → MainWindow: click all nav sections, rotate themes, check footer."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    username, password = _load_rbac_local_credentials()
    store, data_dir = isolated_secure_store
    reset_auth_manager()

    import db_storage_manager.themes.manager as theme_mod
    from db_storage_manager.security import auth as auth_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None
    auth_mod._auth_manager = AuthenticationManager(store=store)

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    bootstrap_admin(username, password, store=store)
    get_auth_manager().reload()
    assert get_auth_manager().is_rbac_active()
    assert get_auth_manager().current_user is None

    from db_storage_manager.gui.login import LoginDialog
    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.themes.manager import get_theme_manager

    # Same path as db_storage_manager.main: LoginDialog then MainWindow
    dlg = LoginDialog()
    dlg.show()
    app.processEvents()
    dlg.username_edit.setText(username)
    dlg.password_edit.setText(password)
    dlg._try_login()
    app.processEvents()
    assert dlg.result() == int(QDialog.DialogCode.Accepted)
    assert get_auth_manager().current_user is not None
    assert get_auth_manager().current_user.username == username
    dlg.close()

    get_theme_manager().set_theme("dark")
    window = MainWindow()
    window.show()
    app.processEvents()

    assert window.tab_widget.count() == _NAV_SECTION_COUNT
    assert len(window.sidebar._buttons) == _NAV_SECTION_COUNT
    assert not window.tab_widget.tabBar().isVisible()

    footer = window.sidebar.footer.text()
    assert username in footer
    assert "Signed in" in footer or username in window.statusBar().currentMessage()

    for index in range(_NAV_SECTION_COUNT):
        window.sidebar._buttons[index].click()
        app.processEvents()
        assert window.tab_widget.currentIndex() == index
        assert window.sidebar._buttons[index].isChecked()
        assert window.tab_widget.widget(index) is not None
        assert window.tab_widget.widget(index).isVisible()

    for theme_key in _THEME_KEYS:
        combo_index = window.settings_widget.theme_combo.findData(theme_key)
        assert combo_index >= 0, f"theme {theme_key} missing from Settings combo"
        window.settings_widget.theme_combo.setCurrentIndex(combo_index)
        app.processEvents()
        assert get_theme_manager().current_theme == theme_key
        sheet = window.styleSheet()
        assert "NavSidebar" in sheet
        assert THEMES[theme_key]["colors"]["primary"] in sheet
        # Glass panels refresh with the active theme (no stale Atmospheric ink).
        assert (
            THEMES[theme_key]["colors"]["surface_elevated"]
            in window.dashboard.styleSheet()
        )
        # Nav still coherent after theme apply
        target = (window.tab_widget.currentIndex() + 1) % _NAV_SECTION_COUNT
        window.sidebar._buttons[target].click()
        app.processEvents()
        assert window.tab_widget.currentIndex() == target
        assert username in window.sidebar.footer.text()

    window.close()


def test_onscreen_theme_visual_smoke_post_login(isolated_secure_store, monkeypatch):
    """When DISPLAY is set: short post-login grab for Atmospheric / Light / Dracula.

    Run in a fresh process without QT_QPA_PLATFORM=offscreen, e.g.::

        pytest tests/test_gui_shell.py::test_onscreen_theme_visual_smoke_post_login -q
    """
    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        pytest.skip("no DISPLAY — on-screen theme smoke not available")
    if os.environ.get("QT_QPA_PLATFORM", "").strip() == "offscreen":
        pytest.skip("QT_QPA_PLATFORM=offscreen — skipping on-screen smoke")

    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

    if QApplication.instance() is not None:
        # Platform plugin is fixed at first QApplication; sibling offscreen tests
        # in the same process make a true on-screen grab unreliable.
        pytest.skip("QApplication already running — use a dedicated pytest process")

    username, password = _load_rbac_local_credentials()
    store, data_dir = isolated_secure_store
    reset_auth_manager()

    import db_storage_manager.themes.manager as theme_mod
    from db_storage_manager.security import auth as auth_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None
    auth_mod._auth_manager = AuthenticationManager(store=store)

    app = QApplication([])
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    bootstrap_admin(username, password, store=store)
    get_auth_manager().reload()

    from db_storage_manager.gui.login import LoginDialog
    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.themes.manager import get_theme_manager

    dlg = LoginDialog()
    dlg.show()
    app.processEvents()
    dlg.username_edit.setText(username)
    dlg.password_edit.setText(password)
    dlg._try_login()
    app.processEvents()
    assert dlg.result() == int(QDialog.DialogCode.Accepted)
    assert get_auth_manager().current_user is not None
    dlg.close()

    artifact_root = Path(
        os.environ.get(
            "DSM_THEME_ARTIFACT_DIR",
            str(_REPO_ROOT / "artifacts" / "theme_visual"),
        )
    )
    artifact_root.mkdir(parents=True, exist_ok=True)

    get_theme_manager().set_theme("dark")
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()

    for theme_key in _THEME_KEYS:
        get_theme_manager().set_theme(theme_key)
        window._on_theme_changed(theme_key)
        app.processEvents()
        colors = THEMES[theme_key]["colors"]
        assert colors["primary"] in window.styleSheet()
        assert colors["surface_elevated"] in window.dashboard.styleSheet()

        # Sample polished surfaces: dashboard cards + dense connections + headers
        for index in (0, 1, 6):
            window.sidebar._buttons[index].click()
            app.processEvents()
            page = window.tab_widget.widget(index)
            title = page.findChild(QLabel, "PageTitle")
            assert title is not None and title.isVisible()
            grab = window.grab()
            assert not grab.isNull() and grab.width() >= 800
            out = artifact_root / f"onscreen_{theme_key}_tab{index}.png"
            assert grab.save(str(out))

        if theme_key == "dark":
            assert window.dashboard._metric_cards["total_size"].objectName() == (
                "MetricCard"
            )
        if theme_key == "light":
            window.sidebar._buttons[1].click()
            app.processEvents()
            assert window.connections_widget.table.objectName() == "DenseTable"

    window.close()
