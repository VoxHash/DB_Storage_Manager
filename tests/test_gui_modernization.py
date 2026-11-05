"""Liquid-glass tokens, accessible icon controls and plugin license UI (offscreen)."""

from __future__ import annotations

import os

import pytest

from db_storage_manager.gui.utils import build_app_stylesheet, rgba
from db_storage_manager.themes.themes import THEMES

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_GLASS_KEYS = (
    "tint_top",
    "tint_bottom",
    "highlight",
    "shadow",
    "solid_background",
    "solid_border",
)


def _lum(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _blend(fg: str, bg: str, alpha: float) -> str:
    f = fg.lstrip("#")
    b = bg.lstrip("#")
    out = [
        round(int(f[i : i + 2], 16) * alpha + int(b[i : i + 2], 16) * (1 - alpha))
        for i in (0, 2, 4)
    ]
    return "#{:02X}{:02X}{:02X}".format(*out)


@pytest.mark.parametrize("theme_key", sorted(THEMES))
def test_theme_text_tokens_meet_wcag_aa(theme_key):
    colors = THEMES[theme_key]["colors"]
    for fg, bg in (
        ("text", "background"),
        ("text", "surface"),
        ("text_secondary", "surface"),
        ("text_secondary", "background"),
        ("text_secondary", "sidebar_bg"),
        ("text_secondary", "row_alt"),
        ("on_primary", "primary"),
        ("primary", "sidebar_bg"),
        ("success", "surface"),
        ("error", "surface"),
        ("warning", "surface"),
    ):
        ratio = _contrast(colors[fg], colors[bg])
        assert ratio >= 4.5, f"{theme_key}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme_key", sorted(THEMES))
def test_active_nav_pill_keeps_contrast(theme_key):
    colors = THEMES[theme_key]["colors"]
    pill = _blend(colors["primary"], colors["sidebar_bg"], 0.16)
    assert _contrast(colors["primary"], pill) >= 4.5


@pytest.mark.parametrize("theme_key", sorted(THEMES))
def test_glass_tokens_present_and_flat_fallback(theme_key):
    glass = THEMES[theme_key]["glassmorphism"]
    for key in _GLASS_KEYS:
        assert glass.get(key), f"{theme_key} missing glass token {key}"
    colors = THEMES[theme_key]["colors"]
    sheet = build_app_stylesheet(colors, glass)
    assert "qlineargradient" in sheet
    assert glass["tint_top"] in sheet and glass["tint_bottom"] in sheet
    assert rgba(colors["primary"], 0.16) in sheet  # translucent active pill
    flat = build_app_stylesheet(colors)
    assert rgba(colors["primary"], 0.16) not in flat  # no glass tokens -> opaque


def test_reduce_transparency_flattens_glass(tmp_path, monkeypatch):
    import db_storage_manager.themes.manager as theme_mod

    monkeypatch.setattr(theme_mod, "THEME_FILE", tmp_path / "theme.json")
    monkeypatch.delenv("DSM_REDUCE_TRANSPARENCY", raising=False)
    manager = theme_mod.ThemeManager()
    manager.set_theme("dark")
    assert manager.get_glass()["tint_top"] != manager.get_glass()["tint_bottom"]

    manager.set_reduce_transparency(True)
    flat = manager.get_glass()
    assert flat["tint_top"] == flat["tint_bottom"] == THEMES["dark"]["glassmorphism"]["solid_background"]
    sheet = build_app_stylesheet(THEMES["dark"]["colors"], flat)
    assert rgba(THEMES["dark"]["colors"]["primary"], 0.16) not in sheet

    # persisted + reloaded
    assert theme_mod.ThemeManager().reduce_transparency is True
    manager.set_reduce_transparency(False)
    monkeypatch.setenv("DSM_REDUCE_TRANSPARENCY", "1")
    assert manager.is_transparency_reduced() is True


def test_focus_ring_and_icon_only_rules_in_stylesheet():
    sheet = build_app_stylesheet(THEMES["dark"]["colors"])
    assert "QPushButton:focus" in sheet
    assert 'QPushButton[iconOnly="true"]' in sheet


@pytest.fixture
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_every_icon_renders_visible_pixels(qapp):
    from db_storage_manager.gui.icons import ICON_NAMES, build_icon

    for name in ICON_NAMES:
        icon = build_icon(name, "#FFFFFF")
        image = icon.pixmap(18, 18).toImage()
        opaque = sum(
            1
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 40
        )
        assert opaque > 10, f"icon '{name}' renders blank"


def test_set_icon_only_is_accessible(qapp):
    from PyQt6.QtWidgets import QPushButton

    from db_storage_manager.gui.icons import ICON_ONLY_SIZE, set_icon_only

    button = QPushButton("Refresh")
    set_icon_only(button, "refresh", "Refresh list")
    assert button.text() == ""
    assert not button.icon().isNull()
    assert button.toolTip() == "Refresh list"
    assert button.accessibleName() == "Refresh list"
    assert button.width() >= 24 and button.width() == ICON_ONLY_SIZE
    with pytest.raises(ValueError):
        set_icon_only(QPushButton(), "refresh", "  ")
    with pytest.raises(KeyError):
        from db_storage_manager.gui.icons import build_icon

        build_icon("does-not-exist", "#fff")


@pytest.fixture
def window(qapp, isolated_secure_store, monkeypatch, tmp_path):
    store, data_dir = isolated_secure_store
    from db_storage_manager.security.auth import reset_auth_manager

    reset_auth_manager()
    import db_storage_manager.config as config_mod
    import db_storage_manager.themes.manager as theme_mod

    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config_mod, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(theme_mod, "THEME_FILE", data_dir / "theme.json")
    theme_mod._theme_manager = None

    from db_storage_manager.gui.main_window import MainWindow

    theme_mod.get_theme_manager().set_theme("dark")
    win = MainWindow()
    win.show()
    yield win
    win.close()
    theme_mod._theme_manager = None


def test_sidebar_has_icons_and_keeps_text(window):
    for btn in window.sidebar._buttons:
        assert not btn.icon().isNull()
        assert btn.text().strip(), "nav entries keep their visible label"
        assert btn.accessibleName() == btn.text()


def test_compact_actions_are_icon_only_and_accessible(window):
    candidates = (
        window.connections_widget.edit_button,
        window.monitoring_widget.refresh_button,
        window.backups_widget.schedule_refresh_button,
        window.plugins_widget.refresh_btn,
    )
    for button in candidates:
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.toolTip().strip()
        assert button.accessibleName().strip()
        # stays a compact hit target (>= 24px) in the real themed window
        assert 24 <= button.width() <= 40 and 24 <= button.height() <= 40


def test_critical_actions_keep_text_labels(window):
    critical = (
        window.connections_widget.delete_button,
        window.plugins_widget.uninstall_btn,
        window.plugins_widget.enable_btn,
        window.plugins_widget.disable_btn,
        window.plugins_widget.activate_license_btn,
        window.plugins_widget.deactivate_license_btn,
    )
    for button in critical:
        assert button.text().strip(), f"{button.objectName() or button} lost its label"
    menu = window.backups_widget.context_menu_entries(1)
    labels = [label for _kind, label, _enabled in menu]
    restore = next(label for kind, label, _enabled in menu if kind == "restore")
    assert "restore" in restore.lower() or "restaur" in restore.lower()
    assert "experimental" not in restore.lower()
    assert any("dry" in label.lower() for label in labels)
    toolbar = []
    layout = window.backups_widget._restore_actions
    for index in range(layout.count()):
        child = layout.itemAt(index).widget()
        if child is not None and child.text().strip():
            toolbar.append(child.text().lower())
    joined = " ".join(toolbar)
    assert "refresh" in joined
    assert "restore" not in joined
    assert "dry-run" not in joined
    assert "delete" not in joined


def test_theme_switch_repaints_icons_and_restyles(window):
    from db_storage_manager.themes.manager import get_theme_manager

    before = window.sidebar._buttons[0].icon().pixmap(18, 18).toImage()
    get_theme_manager().set_theme("light")
    window._on_theme_changed("light")
    assert "NavSidebar" in window.styleSheet()
    assert "qlineargradient" in window.styleSheet()
    after = window.sidebar._buttons[0].icon().pixmap(18, 18).toImage()
    assert after != before, "nav icon was not re-coloured for the new theme"
    get_theme_manager().set_reduce_transparency(True)
    window._on_theme_changed("light")
    assert rgba(THEMES["light"]["colors"]["primary"], 0.16) not in window.styleSheet()


def test_settings_reduce_transparency_toggle(window):
    from db_storage_manager.themes.manager import get_theme_manager

    check = window.settings_widget.reduce_transparency_check
    assert check.text().strip()
    check.setChecked(True)
    assert get_theme_manager().reduce_transparency is True
    assert rgba(
        THEMES[get_theme_manager().current_theme]["colors"]["primary"], 0.16
    ) not in window.styleSheet()
    check.setChecked(False)
    assert get_theme_manager().reduce_transparency is False


def test_plugins_tab_shows_license_state_and_blocks_enable(window, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    widget = window.plugins_widget
    mp = widget.marketplace
    mp.sync_builtins()
    data = mp._read_registry()
    data["plugins"]["pro_report"] = {
        "id": "pro_report",
        "source": "path",
        "module": None,
        "path": None,
        "origin": "test",
        "installed_at": "2026-01-01T00:00:00+00:00",
        "manifest": {
            "id": "pro_report",
            "name": "Pro Report",
            "version": "1.0.0",
            "author": "VoxHash Technologies",
            "description": "Premium reporting plugin",
            "plugin_type": "custom",
            "entry": "plugin:ProReport",
            "license": {
                "required": True,
                "provider": "licensechain",
                "product_id": "11111111-2222-3333-4444-555555555555",
                "purchase_url": "https://pay.licensechain.app/checkout/11111111-2222-3333-4444-555555555555",
            },
        },
    }
    mp._write_registry(data)
    widget.refresh()

    ids = [widget.table.item(r, 0).text() for r in range(widget.table.rowCount())]
    row = ids.index("pro_report")
    assert widget.table.horizontalHeaderItem(6).text() == "License"
    assert widget.table.item(row, 6).text() == "Not activated"
    assert widget.table.item(ids.index("migration"), 6).text() == "Free"
    assert widget.table.item(ids.index("data_comparison"), 6).text() == "Free"

    shown = {}
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: shown.setdefault("msg", a[2])
    )
    widget.table.selectRow(row)
    widget.enable_btn.click()
    assert "premium plugin" in shown["msg"]
    assert "pro_report" in shown["msg"]
    assert mp.get_enabled_map().get("pro_report") is not True


def test_plugins_tab_sponsor_button_opens_github_sponsors(window, monkeypatch):
    from PyQt6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    btn = window.plugins_widget.sponsor_btn
    assert btn.text() == "Support DSM"
    assert "free" in btn.toolTip().lower()
    btn.click()
    assert opened == ["https://github.com/sponsors/VoxHash"]
