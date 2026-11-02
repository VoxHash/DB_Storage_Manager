"""Desktop / Wayland identity must stay distinct from sibling VoxHash Python GUIs."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from db_storage_manager.desktop_identity import (
    APP_DISPLAY_NAME,
    APP_NAME,
    DESKTOP_FILE_ID,
    ICON_NAME,
    ORGANIZATION_DOMAIN,
    ORGANIZATION_NAME,
    SINGLE_INSTANCE_KEY,
    STARTUP_WM_CLASS,
    apply_desktop_identity,
    configure_qt_identity,
)


SIBLING_APP_NAMES = {
    "Telegram Multi-Account Message Sender",
    "ForexSmartBot",
    "HandForge",
    "YTSDownloader",
    "python3",
    "python",
}

SIBLING_DESKTOP_IDS = {
    "dev.voxhash.telegram-multi-account-sender",
    "telegram-multi-account-sender",
    "forexsmartbot",
    "dev.voxhash.HandForge",
    "ytsdownloader",
    "db-storage-manager",  # legacy short id — must not be reused
    "python3",
    "python",
}


def test_constants_are_unique_and_stable():
    assert ORGANIZATION_NAME == "VoxHash"
    assert ORGANIZATION_DOMAIN == "db-storage-manager.voxhash.dev"
    assert APP_NAME == "DB Storage Manager"
    assert APP_DISPLAY_NAME == APP_NAME
    assert DESKTOP_FILE_ID == "dev.voxhash.db-storage-manager"
    assert STARTUP_WM_CLASS == DESKTOP_FILE_ID
    assert ICON_NAME == "db-storage-manager"
    assert SINGLE_INSTANCE_KEY == "dev.voxhash.db-storage-manager.single-instance"
    assert "python" not in DESKTOP_FILE_ID.lower()
    assert APP_NAME not in SIBLING_APP_NAMES
    assert DESKTOP_FILE_ID not in SIBLING_DESKTOP_IDS
    assert SINGLE_INSTANCE_KEY not in {
        "dev.voxhash.HandForge.single-instance",
        "dev.voxhash.telegram-multi-account-sender.single-instance",
    }


def test_apply_sets_desktop_file_name_and_org():
    app = MagicMock()
    apply_desktop_identity(app, version="1.0.6")

    app.setOrganizationName.assert_called_once_with(ORGANIZATION_NAME)
    app.setOrganizationDomain.assert_called_once_with(ORGANIZATION_DOMAIN)
    app.setApplicationName.assert_called_once_with(APP_NAME)
    app.setApplicationDisplayName.assert_called_once_with(APP_DISPLAY_NAME)
    app.setApplicationVersion.assert_called_once_with("1.0.6")
    app.setDesktopFileName.assert_called_once_with(DESKTOP_FILE_ID)


@pytest.fixture(scope="module")
def qapp_identity():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    if QApplication.instance() is None:
        configure_qt_identity("1.0.6")
        app = QApplication([])
    else:
        app = QApplication.instance()
        apply_desktop_identity(app, "1.0.6")
    return app


def test_qt_identity_fields(qapp_identity):
    app = qapp_identity
    assert app.organizationName() == ORGANIZATION_NAME
    assert app.organizationDomain() == ORGANIZATION_DOMAIN
    assert app.applicationName() == APP_NAME
    assert app.applicationDisplayName() == APP_DISPLAY_NAME
    assert app.desktopFileName() == DESKTOP_FILE_ID


def test_packaged_desktop_startup_wmclass_matches():
    desktop = (
        Path(__file__).resolve().parents[1]
        / "packaging"
        / "linux"
        / "dev.voxhash.db-storage-manager.desktop"
    ).read_text(encoding="utf-8")
    assert f"StartupWMClass={STARTUP_WM_CLASS}" in desktop
    assert f"Name={APP_NAME}" in desktop
    assert f"Icon={ICON_NAME}" in desktop
    assert "StartupWMClass=python" not in desktop
    assert "StartupWMClass=db-storage-manager" not in desktop


def test_install_script_targets_reverse_dns_desktop_id():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "install-local-shims.sh"
    ).read_text(encoding="utf-8")
    assert "dev.voxhash.db-storage-manager.desktop" in script
    assert 'rm -f "${APPS_DIR}/db-storage-manager.desktop"' in script


def test_user_data_dir_is_app_specific():
    from db_storage_manager.config import USER_DATA_DIR

    assert "db-storage-manager" in str(USER_DATA_DIR)
    assert "telegram" not in str(USER_DATA_DIR).lower()
