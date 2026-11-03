"""Scheduled backup manager: CRUD e2e, tag isolation, encrypted passphrase vault."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from db_storage_manager.backups import scheduler as scheduler_mod
from db_storage_manager.backups.scheduler import ScheduledBackupManager


@pytest.fixture
def isolated_schedules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_secure_store
):
    path = tmp_path / "scheduled_backups.json"
    monkeypatch.setattr(scheduler_mod, "SCHEDULED_BACKUPS_FILE", path)
    mgr = ScheduledBackupManager()
    yield mgr
    mgr.stop()


def _payload(name: str, minutes: int = 60, **extra):
    data = {
        "name": name,
        "intervalMinutes": minutes,
        "enabled": True,
        "adapterType": "local",
        "adapterConfig": {},
        "connections": ["c1"],
    }
    data.update(extra)
    return data


def test_add_list_toggle_remove(isolated_schedules: ScheduledBackupManager):
    mgr = isolated_schedules
    a = mgr.create_schedule(_payload("A"))
    assert [s.name for s in mgr.get_schedules()] == ["A"]
    assert mgr.is_scheduled(a.id)

    payload = _payload("A", enabled=False)
    payload["id"] = a.id
    mgr.update_schedule(payload)
    assert not mgr.is_scheduled(a.id)
    assert mgr.get_schedule(a.id).enabled is False

    payload["enabled"] = True
    mgr.update_schedule(payload)
    assert mgr.is_scheduled(a.id)

    mgr.delete_schedule(a.id)
    assert mgr.get_schedules() == []
    assert not mgr.is_scheduled(a.id)

    # Persisted state follows every mutation and reloads in a fresh manager.
    again = ScheduledBackupManager()
    assert again.get_schedules() == []


def test_stop_one_schedule_preserves_other(isolated_schedules: ScheduledBackupManager):
    mgr = isolated_schedules
    a = mgr.create_schedule(_payload("A", 60))
    b = mgr.create_schedule(_payload("B", 120, connections=["c2"]))
    assert mgr.is_scheduled(a.id) and mgr.is_scheduled(b.id)
    mgr.delete_schedule(a.id)
    assert not mgr.is_scheduled(a.id)
    assert mgr.is_scheduled(b.id)


def test_passphrase_goes_to_encrypted_vault_not_json(
    isolated_schedules: ScheduledBackupManager, tmp_path: Path
):
    mgr = isolated_schedules
    secret = "correct horse battery staple"
    item = mgr.create_schedule(
        _payload(
            "Proton nightly",
            adapterType="protondrive",
            adapterConfig={"encryption": True, "encryptionKey": secret},
        )
    )
    on_disk = (tmp_path / "scheduled_backups.json").read_text()
    assert secret not in on_disk
    assert "encryptionKey" not in on_disk
    assert mgr.has_encryption_key(item.id)
    assert mgr._load_secret(item.id) == secret

    mgr.delete_schedule(item.id)
    assert not mgr.has_encryption_key(item.id)


def test_legacy_plaintext_key_is_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_secure_store
):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-1",
                    "name": "legacy",
                    "intervalMinutes": 30,
                    "enabled": False,
                    "adapterType": "protondrive",
                    "adapterConfig": {"encryption": True, "encryptionKey": "s3cret"},
                    "connections": ["c1"],
                }
            ]
        )
    )
    monkeypatch.setattr(scheduler_mod, "SCHEDULED_BACKUPS_FILE", path)
    mgr = ScheduledBackupManager()
    assert "s3cret" not in path.read_text()
    assert mgr._load_secret("legacy-1") == "s3cret"


def _sqlite_connection():
    return {
        "id": "c1",
        "name": "lab",
        "type": "sqlite",
        "host": "",
        "port": 0,
        "database": ":memory:",
        "username": "",
        "password": "",
    }


def test_proton_schedule_skips_without_encryption_key(
    isolated_schedules: ScheduledBackupManager, monkeypatch: pytest.MonkeyPatch
):
    calls = []

    async def fake_batch(*_a, **_k):
        calls.append(True)
        return []

    monkeypatch.setattr(
        isolated_schedules.backup_manager, "create_batch_backups", fake_batch
    )
    monkeypatch.setattr(
        isolated_schedules.secure_store, "get_connections", lambda: [_sqlite_connection()]
    )
    monkeypatch.setattr(
        isolated_schedules.backup_manager, "get_adapter", lambda *_a, **_k: object()
    )

    schedule = isolated_schedules.create_schedule(
        _payload(
            "Proton nightly",
            adapterType="protondrive",
            adapterConfig={"encryption": True},  # no passphrase stored
        )
    )
    isolated_schedules._execute_backup(schedule)
    assert calls == []


def test_proton_schedule_runs_with_vaulted_passphrase(
    isolated_schedules: ScheduledBackupManager, monkeypatch: pytest.MonkeyPatch
):
    seen = {}

    async def fake_batch(_connections, _adapter, options):
        seen.update(options)
        return []

    monkeypatch.setattr(
        isolated_schedules.backup_manager, "create_batch_backups", fake_batch
    )
    monkeypatch.setattr(
        isolated_schedules.secure_store, "get_connections", lambda: [_sqlite_connection()]
    )
    monkeypatch.setattr(
        isolated_schedules.backup_manager, "get_adapter", lambda *_a, **_k: object()
    )
    schedule = isolated_schedules.create_schedule(
        _payload(
            "Proton nightly",
            adapterType="protondrive",
            adapterConfig={"encryptionKey": "vault-pass"},
        )
    )
    isolated_schedules._execute_backup(schedule)
    assert seen["encryption"] is True
    assert seen["encryptionKey"] == "vault-pass"


def test_dispatch_skips_overlapping_run(
    isolated_schedules: ScheduledBackupManager, monkeypatch: pytest.MonkeyPatch
):
    mgr = isolated_schedules
    item = mgr.create_schedule(_payload("slow"))
    started = threading.Event()
    release = threading.Event()
    runs = []

    def slow(_item):
        runs.append(1)
        started.set()
        release.wait(5)

    monkeypatch.setattr(mgr, "_execute_backup", slow)
    assert mgr.run_now(item.id) is True
    assert started.wait(5)
    assert mgr.run_now(item.id) is False  # still running: no pile-up
    release.set()
    for _ in range(100):
        if mgr.run_now(item.id):
            break
        threading.Event().wait(0.02)
    release.set()
    assert len(runs) >= 1
    assert mgr.run_now("missing-id") is False
