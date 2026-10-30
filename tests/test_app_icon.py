"""Offscreen checks that the packaged application icon loads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_icon_assets_exist_on_disk():
    root = (
        Path(__file__).resolve().parents[1]
        / "db_storage_manager"
        / "resources"
        / "icons"
    )
    assert (root / "db-storage-manager.svg").is_file()
    assert (root / "db-storage-manager.ico").is_file()
    for size in (16, 32, 48, 64, 128, 256):
        path = root / f"db-storage-manager-{size}.png"
        assert path.is_file(), f"missing {path.name}"
        assert path.stat().st_size > 0


def test_load_app_icon_not_null():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    assert app is not None

    from db_storage_manager.resources import load_app_icon

    icon = load_app_icon()
    assert not icon.isNull()
    assert len(icon.availableSizes()) >= 1


def test_main_window_and_login_receive_icon():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from db_storage_manager.gui.login import LoginDialog
    from db_storage_manager.gui.main_window import MainWindow
    from db_storage_manager.resources import load_app_icon

    expected = load_app_icon()
    assert not expected.isNull()

    login = LoginDialog()
    assert not login.windowIcon().isNull()

    window = MainWindow()
    assert not window.windowIcon().isNull()
