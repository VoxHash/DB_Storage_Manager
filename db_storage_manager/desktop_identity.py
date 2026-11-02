"""Linux / Qt desktop identity for process and window-manager isolation.

Without a unique desktop-file id, Wayland/KDE sees this process as generic
``python3`` and groups or closes it with sibling VoxHash Python GUIs
(e.g. Telegram Multi-Account Message Sender).

Call :func:`configure_qt_identity` **before** constructing ``QApplication``.
"""

from __future__ import annotations

# Freedesktop desktop entry basename (db-storage-manager.desktop) — Wayland app_id.
DESKTOP_FILE_ID = "db-storage-manager"
ORGANIZATION_NAME = "VoxHash"
ORGANIZATION_DOMAIN = "db-storage-manager.voxhash.dev"
STARTUP_WM_CLASS = DESKTOP_FILE_ID


def configure_qt_identity(app_name: str, version: str) -> None:
    """Set unique org/app/desktop ids before ``QApplication(...)`` is created."""
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtGui import QGuiApplication

    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setOrganizationDomain(ORGANIZATION_DOMAIN)
    QCoreApplication.setApplicationName(app_name)
    QCoreApplication.setApplicationVersion(version)
    QGuiApplication.setApplicationDisplayName(app_name)
    QGuiApplication.setDesktopFileName(DESKTOP_FILE_ID)


def apply_desktop_identity(app, app_name: str, version: str) -> None:
    """Instance-level mirror of :func:`configure_qt_identity`."""
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setOrganizationDomain(ORGANIZATION_DOMAIN)
    app.setApplicationName(app_name)
    app.setApplicationDisplayName(app_name)
    app.setApplicationVersion(version)
    app.setDesktopFileName(DESKTOP_FILE_ID)
