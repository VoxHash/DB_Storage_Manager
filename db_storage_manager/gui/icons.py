"""
Vector UI icons drawn with ``QPainter`` (no bundled image assets).

Icons are stroke glyphs on a 24x24 grid, re-coloured from the active theme
tokens so they stay legible in Atmospheric / Light / Dracula. They are used
for navigation and for *non-critical* compact actions (refresh, edit).

Accessibility rule enforced by :func:`set_icon_only`: an icon-only button always
gets a tooltip **and** an accessible name. Destructive, experimental and
RBAC-sensitive actions (Restore, Delete, Uninstall, Activate License ...) keep
their text label and must not be converted.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QWidget

from ..themes.manager import get_theme_manager

_GRID = 24.0
_RENDER_SCALE = 2  # render at 2x so icons stay crisp on HiDPI
DEFAULT_ICON_PX = 18
ICON_ONLY_SIZE = 32  # >= 24px target size (WCAG 2.2 AA, 2.5.8)

_ICON_PROPERTY = "dsmIcon"
_ICON_ONLY_PROPERTY = "iconOnly"


def _rect(p: QPainter, x: float, y: float, w: float, h: float, r: float = 2.0) -> None:
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _poly(p: QPainter, *points: tuple) -> None:
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _dashboard(p: QPainter) -> None:
    _rect(p, 3, 3, 7, 9)
    _rect(p, 14, 3, 7, 5)
    _rect(p, 14, 12, 7, 9)
    _rect(p, 3, 16, 7, 5)


def _connections(p: QPainter) -> None:
    _rect(p, 2.5, 3, 19, 8, 2)
    _rect(p, 2.5, 13, 19, 8, 2)
    _line(p, 6.5, 7, 6.5, 7.01)
    _line(p, 6.5, 17, 6.5, 17.01)


def _query(p: QPainter) -> None:
    _poly(p, (4, 17), (10, 11), (4, 5))
    _line(p, 12, 19, 20, 19)


def _backups(p: QPainter) -> None:
    _rect(p, 2.5, 3, 19, 5, 1.5)
    path = QPainterPath(QPointF(4.5, 8))
    path.lineTo(4.5, 19)
    path.quadTo(4.5, 21, 6.5, 21)
    path.lineTo(17.5, 21)
    path.quadTo(19.5, 21, 19.5, 19)
    path.lineTo(19.5, 8)
    p.drawPath(path)
    _line(p, 10, 12, 14, 12)


def _monitoring(p: QPainter) -> None:
    _poly(p, (22, 12), (18, 12), (15, 21), (9, 3), (6, 12), (2, 12))


def _plugins(p: QPainter) -> None:
    _line(p, 9, 2.5, 9, 8)
    _line(p, 15, 2.5, 15, 8)
    _line(p, 12, 17, 12, 21.5)
    path = QPainterPath(QPointF(6, 8))
    path.lineTo(18, 8)
    path.lineTo(18, 13)
    path.cubicTo(18, 15.2, 16.2, 17, 14, 17)
    path.lineTo(10, 17)
    path.cubicTo(7.8, 17, 6, 15.2, 6, 13)
    path.closeSubpath()
    p.drawPath(path)


def _settings(p: QPainter) -> None:
    for y, knob in ((6, 9), (12, 15), (18, 8)):
        _line(p, 4, y, 20, y)
        p.save()
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(knob, y), 2.2, 2.2)
        p.restore()


def _refresh(p: QPainter) -> None:
    p.drawArc(QRectF(3, 3, 18, 18), 0, -270 * 16)
    path = QPainterPath(QPointF(12, 3))
    path.cubicTo(14.52, 3, 16.93, 4, 18.74, 5.74)
    path.lineTo(21, 8)
    p.drawPath(path)
    _poly(p, (21, 3), (21, 8), (16, 8))


def _edit(p: QPainter) -> None:
    _poly(p, (4, 20), (5.2, 14.8), (16, 4), (20, 8), (9.2, 18.8), (4, 20))
    _line(p, 13.5, 6.5, 17.5, 10.5)


def _save(p: QPainter) -> None:
    _rect(p, 4, 3, 16, 18, 1.5)
    _rect(p, 7, 3, 10, 6, 1)
    _line(p, 8, 14, 16, 14)
    _line(p, 8, 17, 16, 17)


def _key(p: QPainter) -> None:
    p.drawEllipse(QPointF(7.5, 15.5), 5.0, 5.0)
    _line(p, 11.2, 11.8, 21, 2)
    _line(p, 15.5, 7.5, 18.5, 10.5)


def _external(p: QPainter) -> None:
    path = QPainterPath(QPointF(18, 13))
    path.lineTo(18, 19)
    path.quadTo(18, 21, 16, 21)
    path.lineTo(5, 21)
    path.quadTo(3, 21, 3, 19)
    path.lineTo(3, 8)
    path.quadTo(3, 6, 5, 6)
    path.lineTo(11, 6)
    p.drawPath(path)
    _poly(p, (15, 3), (21, 3), (21, 9))
    _line(p, 10, 14, 21, 3)


_DRAWERS: Dict[str, Callable[[QPainter], None]] = {
    "dashboard": _dashboard,
    "connections": _connections,
    "query": _query,
    "backups": _backups,
    "monitoring": _monitoring,
    "plugins": _plugins,
    "settings": _settings,
    "refresh": _refresh,
    "edit": _edit,
    "save": _save,
    "key": _key,
    "external": _external,
}

ICON_NAMES = tuple(_DRAWERS)

# Sidebar section key -> icon name
NAV_ICONS = {
    "dashboard": "dashboard",
    "connections": "connections",
    "query": "query",
    "backups": "backups",
    "monitoring": "monitoring",
    "plugins": "plugins",
    "settings": "settings",
}


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    drawer = _DRAWERS[name]
    px = size * _RENDER_SCALE
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(px / _GRID, px / _GRID)
    pen = QPen(
        QColor(color),
        1.9,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    drawer(painter)
    painter.end()
    pixmap.setDevicePixelRatio(_RENDER_SCALE)
    return pixmap


def build_icon(
    name: str,
    normal: str,
    *,
    active: Optional[str] = None,
    disabled: Optional[str] = None,
    size: int = DEFAULT_ICON_PX,
) -> QIcon:
    """Build a multi-state icon: normal, hover/active, checked (On), disabled."""
    if name not in _DRAWERS:
        raise KeyError(f"unknown icon '{name}'")
    active = active or normal
    disabled = disabled or normal
    icon = QIcon()
    icon.addPixmap(_pixmap(name, normal, size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_pixmap(name, active, size), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_pixmap(name, active, size), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(_pixmap(name, active, size), QIcon.Mode.Active, QIcon.State.On)
    icon.addPixmap(_pixmap(name, disabled, size), QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(_pixmap(name, disabled, size), QIcon.Mode.Disabled, QIcon.State.On)
    return icon


def themed_icon(
    name: str,
    *,
    size: int = DEFAULT_ICON_PX,
    nav: bool = False,
    filled: bool = False,
) -> QIcon:
    """Icon coloured from the current theme tokens.

    ``nav=True`` uses the muted ink at rest and the primary accent when checked
    (sidebar). ``filled=True`` is for buttons painted with the primary fill (the
    tab panels' glass style): the glyph uses ``on_primary`` so it keeps contrast.
    Otherwise the normal ink is the main text colour.
    """
    colors = get_theme_manager().get_theme()["colors"]
    muted = colors["text_secondary"]
    text = colors["text"]
    primary = colors["primary"]
    if filled:
        on_primary = colors["on_primary"]
        return build_icon(name, on_primary, active=on_primary, disabled=muted, size=size)
    return build_icon(
        name,
        muted if nav else text,
        active=primary,
        disabled=muted,
        size=size,
    )


def set_icon_only(
    button: QAbstractButton,
    name: str,
    label: str,
    *,
    tooltip: Optional[str] = None,
) -> None:
    """Turn ``button`` into an accessible icon-only control.

    Sets icon, tooltip, accessible name/description and a >=32px hit target.
    ``label`` is the translated action name (never empty).
    """
    if not label or not label.strip():
        raise ValueError("icon-only buttons need a non-empty accessible label")
    button.setText("")
    button.setIcon(themed_icon(name))
    button.setIconSize(QSize(DEFAULT_ICON_PX, DEFAULT_ICON_PX))
    button.setToolTip(tooltip or label)
    button.setAccessibleName(label)
    button.setAccessibleDescription(tooltip or label)
    button.setFixedSize(ICON_ONLY_SIZE, ICON_ONLY_SIZE)
    button.setProperty(_ICON_PROPERTY, name)
    button.setProperty(_ICON_ONLY_PROPERTY, True)


def set_icon_with_text(button: QAbstractButton, name: str) -> None:
    """Add a leading icon while keeping the visible text label."""
    button.setIcon(themed_icon(name))
    button.setIconSize(QSize(DEFAULT_ICON_PX, DEFAULT_ICON_PX))
    button.setProperty(_ICON_PROPERTY, name)


def _on_primary_fill(button: QAbstractButton) -> bool:
    """True when the button sits inside a ``glassmorphism`` panel (primary-filled buttons)."""
    parent = button.parentWidget()
    while parent is not None:
        if parent.objectName() == "glassmorphism":
            return True
        parent = parent.parentWidget()
    return False


def refresh_icons(root: QWidget, names: Optional[Iterable[str]] = None) -> int:
    """Re-colour every themed icon button under ``root``.

    Call after a theme switch and once after the widget tree is parented, so each
    glyph picks the right ink for its actual background.
    """
    wanted = set(names) if names is not None else None
    count = 0
    for button in root.findChildren(QAbstractButton):
        name = button.property(_ICON_PROPERTY)
        if not name or name not in _DRAWERS:
            continue
        if wanted is not None and name not in wanted:
            continue
        nav = button.objectName() == "NavItem"
        button.setIcon(
            themed_icon(name, nav=nav, filled=not nav and _on_primary_fill(button))
        )
        count += 1
    return count


__all__ = [
    "DEFAULT_ICON_PX",
    "ICON_NAMES",
    "ICON_ONLY_SIZE",
    "NAV_ICONS",
    "build_icon",
    "refresh_icons",
    "set_icon_only",
    "set_icon_with_text",
    "themed_icon",
]
