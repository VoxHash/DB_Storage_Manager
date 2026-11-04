"""v1.0.7: job runner, adapter-aware verify, schedule UI, updates, tray, RBAC, i18n."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "db_storage_manager" / "i18n" / "translations"


def _qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _pump(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return predicate()


# --------------------------------------------------------------------- jobs


def test_job_runner_groups_run_concurrently_and_same_group_serializes():
    app = _qapp()
    from db_storage_manager.gui.jobs import JobRunner

    runner = JobRunner()
    both_running = threading.Barrier(2, timeout=5)
    release = threading.Event()
    results = []

    def make(tag):
        def job():
            both_running.wait()  # only passes if both groups run at once
            release.wait(5)
            return tag

        return job

    assert runner.submit("a", make("a"), results.append)
    assert runner.submit("b", make("b"), results.append)
    # same group while busy is rejected (no duplicate / no kill)
    assert runner.submit("a", lambda: "dup", results.append) is False
    assert runner.is_busy("a") and runner.is_busy("b")
    release.set()
    assert _pump(app, lambda: not runner.any_busy())
    assert sorted(results) == ["a", "b"]


def test_job_runner_queue_keeps_only_newest_pending():
    app = _qapp()
    from db_storage_manager.gui.jobs import JobRunner

    runner = JobRunner()
    gate = threading.Event()
    order = []

    assert runner.submit("g", lambda: (gate.wait(5), "first")[1], order.append)
    assert runner.submit("g", lambda: "second", order.append, queue=True)
    assert runner.submit("g", lambda: "third", order.append, queue=True)
    gate.set()
    assert _pump(app, lambda: not runner.any_busy() and len(order) >= 2)
    assert order == ["first", "third"]


def test_job_runner_reports_failures():
    app = _qapp()
    from db_storage_manager.gui.jobs import JobRunner

    runner = JobRunner()
    errors = []

    def boom():
        raise RuntimeError("kaboom")

    runner.submit("g", boom, lambda _r: None, errors.append)
    assert _pump(app, lambda: bool(errors))
    assert "kaboom" in errors[0]


# ------------------------------------------------------- adapter-aware verify


def _info(path: str, *, remote: bool, sha: str = "abc") -> Any:
    from db_storage_manager.backups.base import BackupInfo

    return BackupInfo(
        id=f"id-{path}",
        name=Path(path).name,
        path=path,
        size=1,
        createdAt=datetime.now(),
        status="completed",
        metadata={"sha256": sha, **({"destination": "protondrive"} if remote else {})},
    )


def test_verify_all_uses_adapter_for_proton_rows_not_local_paths(tmp_path):
    from db_storage_manager.backups.manager import BackupManager

    local_file = tmp_path / "local.db"
    local_file.write_bytes(b"payload")
    import hashlib

    digest = hashlib.sha256(b"payload").hexdigest()

    class FakeProton:
        def __init__(self):
            self.calls = []

        def verify_remote_checksum(self, info):
            self.calls.append(info.path)
            return {
                "ok": True,
                "status": "pass",
                "path": info.path,
                "expected": "abc",
                "actual": "abc",
                "error": None,
            }

    manager = BackupManager()
    fake = FakeProton()
    manager.register_adapter("protondrive", fake)
    remote = _info("protondrive:backups/remote.dsmenc", remote=True)
    local = _info(str(local_file), remote=False, sha=digest)

    results = manager.verify_backups_parallel([remote, local])
    by_id = {r["id"]: r for r in results}
    assert by_id[remote.id]["ok"] is True
    assert by_id[remote.id]["status"] != "not_found"
    assert by_id[local.id]["ok"] is True
    assert fake.calls == ["protondrive:backups/remote.dsmenc"]
    assert manager.is_remote_backup(remote) and not manager.is_remote_backup(local)


# ------------------------------------------------------- backups widget (GUI)


@pytest.fixture
def backups_widget(tmp_path, monkeypatch, isolated_secure_store):
    from db_storage_manager.backups import scheduler as scheduler_mod

    monkeypatch.setattr(
        scheduler_mod, "SCHEDULED_BACKUPS_FILE", tmp_path / "schedules.json"
    )
    app = _qapp()
    from db_storage_manager.gui.backups import BackupsWidget

    connections = [
        {
            "id": "c1",
            "name": "lab-sqlite",
            "type": "sqlite",
            "host": "",
            "port": 0,
            "database": str(tmp_path / "lab.db"),
            "username": "",
            "password": "",
        }
    ]
    widget = BackupsWidget(connections, backup_dir=tmp_path / "bk")
    yield app, widget
    widget.shutdown()
    widget.schedule_manager.stop()
    widget.close()
    app.processEvents()


def test_schedule_connection_combo_is_populated(backups_widget):
    _app, widget = backups_widget
    assert widget.schedule_connection_combo.count() == 1
    assert widget.schedule_connection_combo.itemText(0) == "lab-sqlite"


def test_schedule_add_toggle_remove_through_ui(backups_widget):
    _app, widget = backups_widget
    widget.schedule_name_edit.setText("nightly")
    widget.schedule_passphrase_edit.setText("ui-passphrase")
    widget._add_schedule()
    assert widget.schedules_table.rowCount() == 1
    schedule = widget.schedule_manager.get_schedules()[0]
    assert schedule.name == "nightly" and schedule.enabled
    # passphrase lives in the encrypted vault, never in the schedule JSON
    assert widget.schedule_manager.has_encryption_key(schedule.id)
    assert "encryptionKey" not in json.dumps(schedule.to_dict())

    widget.schedules_table.selectRow(0)
    widget._toggle_selected_schedule()
    assert widget.schedule_manager.get_schedules()[0].enabled is False

    widget.schedules_table.selectRow(0)
    widget._remove_selected_schedule()
    assert widget.schedules_table.rowCount() == 0
    assert widget.schedule_manager.get_schedules() == []


def test_dry_run_of_encrypted_backup_requires_passphrase(backups_widget, monkeypatch):
    _app, widget = backups_widget
    encrypted = _info("/tmp/does-not-matter.dsmenc", remote=False)
    encrypted.metadata["encryption"] = True
    widget._backups = [encrypted]
    widget._populate_table()
    widget.backups_table.selectRow(0)
    widget.encryption_key_edit.setText("")

    prompts = []
    monkeypatch.setattr(
        widget, "_prompt_passphrase", lambda name: prompts.append(name) or None
    )
    widget.dry_run_selected()
    assert prompts == [encrypted.name]  # user is asked, nothing runs without it
    assert not widget._jobs.any_busy()
    assert "passphrase" in widget.verify_status_label.text().lower()


def test_backups_widget_has_no_technical_busy_or_help_text(backups_widget):
    _app, widget = backups_widget
    t = widget.i18n.translate
    assert t("backups.create_in_progress") == "Creating backup…"
    assert t("backups.scheduled_help") == "Schedule recurring dumps."


# ------------------------------------------------------------------ updates


def _release(tag, *, pre=False, url=None):
    return {
        "tag_name": tag,
        "prerelease": pre,
        "draft": False,
        "html_url": url
        or f"https://github.com/VoxHash/DB_Storage_Manager/releases/tag/{tag}",
        "body": "notes",
        "published_at": "2026-01-01T00:00:00Z",
    }


def test_update_channels_stable_vs_experimental():
    from db_storage_manager import updates

    payload = [
        _release("v1.0.7"),
        _release("v1.1.0-rc1", pre=True),
        _release("v1.0.9"),
        _release("v9.9.9", url="https://evil.example/releases/v9.9.9"),
    ]
    releases = updates.parse_releases(payload)
    assert [r.tag for r in releases] == ["v1.1.0-rc1", "v1.0.9", "v1.0.7"]
    stable = updates.select_update("1.0.7", releases, updates.CHANNEL_STABLE)
    exp = updates.select_update("1.0.7", releases, updates.CHANNEL_EXPERIMENTAL)
    assert stable.tag == "v1.0.9"
    assert exp.tag == "v1.1.0-rc1"
    assert updates.select_update("1.0.9", releases, updates.CHANNEL_STABLE) is None
    assert "git+https://github.com/VoxHash/DB_Storage_Manager.git@v1.0.9" in (
        stable.pip_command
    )


def test_check_for_update_uses_only_public_github_endpoint():
    from db_storage_manager import updates

    seen = []

    def fetch(url):
        seen.append(url)
        return json.dumps([_release("v2.0.0")]).encode()

    result = updates.check_for_update("stable", current="1.0.7", fetch=fetch)
    assert result["update"].tag == "v2.0.0"
    assert seen and all(
        u.startswith("https://api.github.com/repos/VoxHash/DB_Storage_Manager/")
        for u in seen
    )


def test_updates_panel_check_and_trusted_open(isolated_secure_store):
    app = _qapp()
    from db_storage_manager import updates
    from db_storage_manager.gui.updates import UpdatesPanel

    opened = []
    releases = updates.parse_releases([_release("v3.0.0")])

    dlg = UpdatesPanel(
        check_fn=lambda channel: {
            "current": "1.0.7",
            "channel": channel,
            "update": releases[0],
            "latest": releases[0],
        },
        changelog_fn=lambda: ("# Changelog\n\n## [1.0.7]", "local"),
        open_url_fn=opened.append,
    )
    dlg.wait_idle()
    assert dlg.changelog_button.text()
    from db_storage_manager.gui.changelog import ChangelogDialog

    changelog = ChangelogDialog(
        changelog_fn=lambda: ("# Changelog\n\n## [1.0.7]", "local")
    )
    assert "Changelog" in changelog.view.toPlainText()
    changelog.close()
    dlg.check_updates()
    dlg.wait_idle()
    app.processEvents()
    assert "3.0.0" in dlg.result_label.text()
    assert dlg.download_button.isEnabled()
    dlg.open_download_page()
    assert opened == [releases[0].html_url]
    dlg.close()


def test_auto_check_is_opt_in_and_rate_limited(isolated_secure_store):
    from datetime import datetime, timedelta, timezone

    from db_storage_manager.gui.updates import UpdatesPanel
    from db_storage_manager.updates import auto_check_due

    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    assert auto_check_due(None, now) is True
    assert auto_check_due(now.isoformat(), now) is False
    assert auto_check_due((now - timedelta(hours=25)).isoformat(), now) is True

    app = _qapp()
    calls = []
    panel = UpdatesPanel(
        check_fn=lambda channel: calls.append(channel)
        or {"update": None, "latest": None},
        changelog_fn=lambda: ("# Changelog", "local"),
    )
    panel.maybe_auto_check()
    panel.wait_idle()
    app.processEvents()
    assert calls == []
    panel.close()


# --------------------------------------------------------------------- tray


def test_tray_clicks_and_notification_timeout():
    app = _qapp()
    from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

    from db_storage_manager.gui.tray import AppTray, clamp_notification_seconds

    window = QWidget()
    window.show()
    sections = []
    tray = AppTray(window, open_section=sections.append, timeout_seconds=5)
    Reason = QSystemTrayIcon.ActivationReason

    tray._on_activated(Reason.Trigger)  # left click hides a visible window
    assert not window.isVisible()
    tray._on_activated(Reason.Trigger)  # and shows it again
    assert window.isVisible()
    window.hide()
    tray._on_activated(Reason.DoubleClick)
    assert window.isVisible()
    tray._on_activated(Reason.MiddleClick)
    assert sections == ["backups"]

    # right click is the platform context menu, with real actions
    assert tray.icon.contextMenu() is tray.menu
    labels = [a.text() for a in tray.menu.actions() if a.text()]
    assert len(labels) >= 6
    assert "Changelog" in labels
    assert "Check for updates" in labels
    assert "Changelog & Updates" not in labels

    shown = {}
    tray.icon.showMessage = lambda title, msg, icon, ms: shown.update(ms=ms)
    tray.notify("t", "m", "critical")
    assert shown["ms"] == 5000
    tray.set_timeout_seconds(12)
    tray.notify("t", "m", "info")
    assert shown["ms"] == 12000
    assert clamp_notification_seconds(0) == 2
    assert clamp_notification_seconds(9999) == 60
    assert clamp_notification_seconds("junk") == 5
    window.close()
    app.processEvents()


def test_closing_the_window_hides_to_tray_until_quit():
    """Offscreen: a tray object is enough. A real tray icon is not required."""
    app = _qapp()
    from db_storage_manager.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    seen = {}

    class _Tray:
        menu = None

        def refresh_status(self):
            seen["refresh"] = seen.get("refresh", 0) + 1

        def hide(self):
            seen["hidden"] = True

        quit_action = type("A", (), {"text": lambda self: "Quit"})()

    window.tray = _Tray()
    window._quitting = False
    window.close()
    app.processEvents()
    assert not window.isVisible()
    assert seen.get("refresh") == 1
    assert "hidden" not in seen
    assert window.tray.quit_action.text() == "Quit"
    window._quitting = True
    window.show()
    window.close()
    app.processEvents()
    assert seen.get("hidden") is True
    window.deleteLater()
    app.processEvents()


# --------------------------------------------------------------------- RBAC


def test_rbac_query_permissions_and_login_throttle(isolated_secure_store):
    from db_storage_manager.security.auth import (
        MAX_FAILED_LOGINS,
        AuthenticationManager,
        UserRole,
    )

    store, _ = isolated_secure_store
    auth = AuthenticationManager(store=store)
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("viewer1", "password123", role=UserRole.VIEWER)
    auth.create_user("op", "password123", role=UserRole.USER)
    auth.logout()

    auth.authenticate("viewer1", "password123")
    assert not auth.has_permission("query:execute")
    assert not auth.has_permission("query:write")
    auth.logout()
    auth.authenticate("op", "password123")
    assert auth.has_permission("query:execute")
    auth.logout()
    auth.authenticate("admin", "password123")
    assert auth.has_permission("query:write")
    auth.logout()

    for _ in range(MAX_FAILED_LOGINS):
        assert auth.authenticate("admin", "wrong-password") is None
    assert auth.is_locked_out("admin")
    # correct password is refused while throttled
    assert auth.authenticate("admin", "password123") is None


# ---------------------------------------------------- drivers / monitoring


def test_mysql_ensure_alive_pings_then_reconnects():
    from db_storage_manager.db.base import ConnectionConfig
    from db_storage_manager.db.mysql import MySQLConnection

    config = ConnectionConfig(
        id="m", name="m", type="mysql", host="h", port=3306, database="d",
        username="u", password="p",
    )
    conn = MySQLConnection(config)

    class Live:
        def __init__(self):
            self.pinged = []

        def ping(self, reconnect=False):
            self.pinged.append(reconnect)

        def close(self):
            pass

    live = Live()
    conn.connection = live
    asyncio.run(conn._ensure_alive())
    assert live.pinged == [True]  # alive: only a reconnecting ping

    class Dead(Live):
        def ping(self, reconnect=False):
            raise RuntimeError("(0, '')")

    reconnects = []

    async def fake_connect():
        reconnects.append(True)
        conn.connection = Live()
        conn.connected = True

    conn.connection = Dead()
    conn.connect = fake_connect
    asyncio.run(conn._ensure_alive())
    assert reconnects == [True]


def test_health_ping_reconnects_once_on_dead_session():
    from db_storage_manager.monitoring.health import HealthChecker

    class Cfg:
        type = "mysql"

    class Conn:
        config = Cfg()
        connected = True

        def __init__(self):
            self.queries = 0
            self.connects = 0

        async def connect(self):
            self.connects += 1

        async def disconnect(self):
            self.connected = False

        async def execute_query(self, sql, safe_mode=True):
            self.queries += 1
            if self.queries == 1:
                raise RuntimeError("InterfaceError (0, '')")
            return "ok"

    conn = Conn()
    checker = HealthChecker(conn)
    assert asyncio.run(checker._ping()) == "ok"
    assert conn.connects == 1 and conn.queries == 2


# --------------------------------------------------------------- i18n / meta


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _load(locale):
    return _flat(json.loads((TRANSLATIONS / f"{locale}.json").read_text("utf-8")))


LOCALES = sorted(p.stem for p in TRANSLATIONS.glob("*.json"))
_PLACEHOLDER = re.compile(r"\{\w+\}")


def test_all_locales_complete_and_placeholders_match_english():
    en = _load("en")
    assert len(LOCALES) >= 11
    for locale in LOCALES:
        if locale == "en":
            continue
        loc = _load(locale)
        missing = sorted(set(en) - set(loc))
        extra = sorted(set(loc) - set(en))
        assert not missing, f"{locale} missing {len(missing)} keys, e.g. {missing[:5]}"
        assert not extra, f"{locale} has keys unknown to en: {extra[:5]}"
        for key, value in en.items():
            assert sorted(_PLACEHOLDER.findall(value)) == sorted(
                _PLACEHOLDER.findall(loc[key])
            ), f"{locale}:{key} placeholder mismatch"


def test_chinese_is_translated_not_english_copy():
    en, zh = _load("en"), _load("zh")
    keys = [
        "backups.proton_ready",
        "backups.proton_configure_title",
        "monitoring.start_monitoring",
        "plugins.title",
        "updates.check",
        "tray.quit",
        "auth.role_admin",
    ]
    for key in keys:
        assert zh[key] != en[key]
        assert re.search(r"[\u4e00-\u9fff]", zh[key]), key


def test_every_code_referenced_key_exists_in_english():
    en = _load("en")
    missing = {}
    for path in (ROOT / "db_storage_manager").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if (
                name in ("t", "translate")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "." in node.args[0].value
                and " " not in node.args[0].value
                and node.args[0].value not in en
            ):
                missing[node.args[0].value] = str(path.relative_to(ROOT))
    assert not missing, missing


def test_english_fallback_for_missing_locale_key(monkeypatch):
    from db_storage_manager.i18n.manager import I18nManager

    manager = I18nManager()
    manager.set_language("zh")
    original = manager.translations["zh"]
    pruned = json.loads(json.dumps(original))
    pruned.get("backups", {}).pop("proton_ready", None)
    manager.translations["zh"] = pruned
    text = manager.translate("backups.proton_ready", remote="r", path="p")
    assert text != "backups.proton_ready"
    assert "Proton Drive ready" in text and "r" in text


def test_about_text_version_year_and_no_built_with():
    from db_storage_manager.config import APP_VERSION

    for locale in LOCALES:
        loc = _load(locale)
        assert "about.built_with" not in loc
        assert loc["about.copyright"] == "© 2026 VOXHASH LABS"
        assert "{version}" in loc["about.version"]
    assert APP_VERSION == "1.0.7"
    blob = json.dumps(_load("en"))
    assert "Built with Python and PyQt6" not in blob


def test_version_is_synced_across_metadata():
    import db_storage_manager
    from db_storage_manager.config import APP_VERSION

    setup_py = (ROOT / "setup.py").read_text("utf-8")
    assert db_storage_manager.__version__ == APP_VERSION == "1.0.7"
    assert 'version="1.0.7"' in setup_py


def test_package_data_ships_translations_and_api_static():
    setup_py = (ROOT / "setup.py").read_text("utf-8")
    assert "i18n/translations/*.json" in setup_py
    assert "api/static/*" in setup_py
    assert list((ROOT / "db_storage_manager" / "api" / "static").glob("*"))
