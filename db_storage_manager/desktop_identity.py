"""Linux / Qt desktop identity for process and window-manager isolation.

Without a unique desktop-file id, Wayland/KDE sees this process as generic
``python3`` and groups or closes it with sibling VoxHash Python GUIs
(e.g. Telegram Multi-Account Message Sender).

Call :func:`configure_qt_identity` **before** constructing ``QApplication``,
and/or :func:`apply_desktop_identity` on the instance before showing windows.

This process is always a separate OS process from ForexSmartBot / HandForge /
Telegram. Closing a Plasma/workspace *panel* or host window only affects those
apps if they share one process (they do not when launched via their own
``.desktop`` / entry points).
"""

from __future__ import annotations

# Freedesktop desktop entry basename (no .desktop) — Wayland app_id / KWin.
# Reverse-DNS matches sibling VoxHash apps (Telegram, HandForge) so Plasma
# never falls back to grouping under a generic ``python`` / short-name collision.
DESKTOP_FILE_ID = "dev.voxhash.db-storage-manager"
# Qt application name (window titles / default QSettings app key).
APP_NAME = "DB Storage Manager"
APP_DISPLAY_NAME = "DB Storage Manager"
ORGANIZATION_NAME = "VoxHash"
# Unique per-app domain so QStandardPaths / default QSettings never collide.
ORGANIZATION_DOMAIN = "db-storage-manager.voxhash.dev"
# Must match packaging/linux/*.desktop StartupWMClass and DESKTOP_FILE_ID.
STARTUP_WM_CLASS = DESKTOP_FILE_ID
# Icon theme name (hicolor) — may differ from desktop-file id.
ICON_NAME = "db-storage-manager"
# Reserved unique key if a QLocalServer single-instance guard is added later.
# Not used today (DSM allows multiple windows); must never match Telegram/HandForge.
SINGLE_INSTANCE_KEY = "dev.voxhash.db-storage-manager.single-instance"


def configure_qt_identity(version: str | None = None) -> None:
    """Set unique org/app/desktop ids before ``QApplication(...)`` is created."""
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtGui import QGuiApplication

    from db_storage_manager import __version__

    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setOrganizationDomain(ORGANIZATION_DOMAIN)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(
        version if version is not None else __version__
    )
    QGuiApplication.setApplicationDisplayName(APP_DISPLAY_NAME)
    QGuiApplication.setDesktopFileName(DESKTOP_FILE_ID)


def apply_desktop_identity(app, version: str | None = None) -> None:
    """Instance-level mirror of :func:`configure_qt_identity` (tests / late bind)."""
    from db_storage_manager import __version__

    app.setOrganizationName(ORGANIZATION_NAME)
    app.setOrganizationDomain(ORGANIZATION_DOMAIN)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(version if version is not None else __version__)
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName(DESKTOP_FILE_ID)
