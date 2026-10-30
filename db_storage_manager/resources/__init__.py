"""Packaged static assets (application icons, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget

_ICON_SIZES = (16, 32, 48, 64, 128, 256, 512)


def icons_dir() -> Path:
    """Directory containing packaged application icon files."""
    return Path(__file__).resolve().parent / "icons"


def app_icon_path(size: Optional[int] = None) -> Path:
    """
    Path to a packaged icon file.

    ``size`` selects ``db-storage-manager-{size}.png``.
    When omitted, returns the multi-size ICO on Windows-friendly layouts,
    else the 256px PNG.
    """
    root = icons_dir()
    if size is not None:
        return root / f"db-storage-manager-{size}.png"
    ico = root / "db-storage-manager.ico"
    if ico.is_file():
        return ico
    return root / "db-storage-manager.png"


def load_app_icon() -> QIcon:
    """Build a multi-resolution ``QIcon`` from packaged PNG assets."""
    icon = QIcon()
    root = icons_dir()
    for size in _ICON_SIZES:
        path = root / f"db-storage-manager-{size}.png"
        if path.is_file():
            icon.addFile(str(path))
    if icon.isNull():
        fallback = root / "db-storage-manager.png"
        if fallback.is_file():
            icon.addFile(str(fallback))
    if icon.isNull():
        svg = root / "db-storage-manager.svg"
        if svg.is_file():
            icon.addFile(str(svg))
    return icon


def apply_app_icon(target: QWidget) -> QIcon:
    """Set the packaged application icon on a window or dialog."""
    icon = load_app_icon()
    if not icon.isNull():
        target.setWindowIcon(icon)
    return icon
