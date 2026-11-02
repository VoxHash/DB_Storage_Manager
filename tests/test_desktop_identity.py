"""Desktop / Wayland identity must stay distinct from sibling VoxHash Python GUIs."""

from db_storage_manager.desktop_identity import (
    DESKTOP_FILE_ID,
    ORGANIZATION_DOMAIN,
    STARTUP_WM_CLASS,
)


def test_desktop_file_id_matches_packaging_and_is_not_python():
    assert DESKTOP_FILE_ID == "db-storage-manager"
    assert STARTUP_WM_CLASS == DESKTOP_FILE_ID
    assert "python" not in DESKTOP_FILE_ID.lower()


def test_organization_domain_is_app_specific():
    assert ORGANIZATION_DOMAIN == "db-storage-manager.voxhash.dev"


def test_packaged_desktop_startup_wmclass_matches():
    from pathlib import Path

    desktop = (
        Path(__file__).resolve().parents[1]
        / "packaging"
        / "linux"
        / "db-storage-manager.desktop"
    ).read_text(encoding="utf-8")
    assert f"StartupWMClass={STARTUP_WM_CLASS}" in desktop
