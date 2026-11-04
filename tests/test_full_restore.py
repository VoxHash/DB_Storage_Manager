"""Experimental full restore: gate, RBAC, confirmation, pre-flight, safety backup, audit."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest

from db_storage_manager import audit, config
from db_storage_manager.backups.base import BackupOptions
from db_storage_manager.backups.local import LocalBackupAdapter
from db_storage_manager.backups.manager import BackupManager, RestoreRefused
from db_storage_manager.backups.pipeline import prepare_payload, unpack_payload
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.experimental import (
    ENV_VAR,
    ExperimentalDisabledError,
    env_forces_experimental,
    is_restore_enabled,
)
from db_storage_manager.native import sha256_file
from db_storage_manager.security.auth import (
    AuthenticationManager,
    PermissionDenied,
    UserRole,
)
import db_storage_manager.security.auth as auth_mod

PASSPHRASE = "restore-test-passphrase"


def _make_db(path: Path, names) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("DELETE FROM items")
        conn.executemany("INSERT INTO items(name) VALUES (?)", [(n,) for n in names])
        conn.commit()
    finally:
        conn.close()


def _names(path: Path):
    conn = sqlite3.connect(str(path))
    try:
        return sorted(r[0] for r in conn.execute("SELECT name FROM items"))
    finally:
        conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_secure_store):
    store, _ = isolated_secure_store
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    monkeypatch.delenv(ENV_VAR, raising=False)
    db = tmp_path / "prod.db"
    _make_db(db, ["alpha", "beta"])
    # Pool keys are connection ids: a unique id per test keeps pooled sessions apart.
    cfg = ConnectionConfig(
        id=f"restore-{tmp_path.name}", name="prod", type="sqlite", database=str(db)
    )
    backups = tmp_path / "backups"
    adapter = LocalBackupAdapter(base_path=backups)
    manager = BackupManager()

    def make_backup(**opts):
        return asyncio.run(manager.create_backup(adapter, cfg, opts))

    return {
        "store": store,
        "db": db,
        "cfg": cfg,
        "backups": backups,
        "adapter": adapter,
        "manager": manager,
        "make_backup": make_backup,
        "tmp": tmp_path,
    }


def _enable(env):
    settings = env["store"].get_settings()
    settings["experimental"] = {"restore": True}
    env["store"].set_settings(settings)


def _restore(env, backup, **kwargs):
    kwargs.setdefault("confirmation", "prod.db")
    return asyncio.run(
        env["manager"].full_restore(env["adapter"], backup, env["cfg"], **kwargs)
    )


def test_restore_is_on_by_default(env):
    assert is_restore_enabled() is True
    backup = env["make_backup"](compression="gzip")
    _make_db(env["db"], ["changed"])
    _restore(env, backup)
    assert _names(env["db"]) == ["alpha", "beta"]


def test_operator_can_turn_restore_off(env):
    settings = env["store"].get_settings()
    settings["experimental"] = {"restore": False}
    env["store"].set_settings(settings)
    assert is_restore_enabled() is False
    backup = env["make_backup"](compression="gzip")
    _make_db(env["db"], ["changed"])
    with pytest.raises(ExperimentalDisabledError):
        _restore(env, backup)
    assert _names(env["db"]) == ["changed"]


def test_environment_variable_forces_restore_on(env, monkeypatch):
    settings = env["store"].get_settings()
    settings["experimental"] = {"restore": False}
    env["store"].set_settings(settings)
    monkeypatch.setenv(ENV_VAR, "1")
    assert env_forces_experimental() is True
    assert is_restore_enabled() is True
    monkeypatch.setenv(ENV_VAR, "0")
    assert env_forces_experimental() is False
    assert is_restore_enabled() is False


def test_restore_requires_rbac_permission(env, monkeypatch):
    _enable(env)
    backup = env["make_backup"](compression="none")
    auth = AuthenticationManager(store=env["store"])
    auth.bootstrap_admin("admin", "password123")
    auth.authenticate("admin", "password123")
    auth.create_user("viewer", "password123", role=UserRole.VIEWER, email="v@x")
    auth.logout()
    auth.authenticate("viewer", "password123")
    monkeypatch.setattr(auth_mod, "_auth_manager", auth)

    _make_db(env["db"], ["changed"])
    with pytest.raises(PermissionDenied):
        _restore(env, backup)
    assert _names(env["db"]) == ["changed"]
    entry = audit.read_audit()[-1]
    assert entry["outcome"] == "refused" and entry["actor"] == "viewer"

    auth.logout()
    auth.authenticate("admin", "password123")
    _restore(env, backup)
    assert _names(env["db"]) == ["alpha", "beta"]


def test_confirmation_must_match_database_name(env):
    _enable(env)
    backup = env["make_backup"]()
    _make_db(env["db"], ["changed"])
    for wrong in ("", "prod", "PROD.DB", str(env["db"]) + "x"):
        with pytest.raises(RestoreRefused, match="Confirmation"):
            _restore(env, backup, confirmation=wrong)
    assert _names(env["db"]) == ["changed"]
    assert BackupManager.restore_confirmation_phrase(env["cfg"]) == "prod.db"


def test_engine_mismatch_is_refused(env):
    _enable(env)
    backup = env["make_backup"]()
    other = ConnectionConfig(
        id="pg", name="warehouse", type="postgresql", host="127.0.0.1", database="wh"
    )
    with pytest.raises(RestoreRefused, match="sqlite"):
        asyncio.run(
            env["manager"].full_restore(
                env["adapter"], backup, other, confirmation="wh"
            )
        )


def test_encrypted_restore_with_safety_backup_and_audit(env):
    _enable(env)
    backup = env["make_backup"](
        compression="zstd", encryption=True, encryptionKey=PASSPHRASE
    )
    assert backup.metadata["encryption"] is True
    # Data drifts after the backup was taken.
    _make_db(env["db"], ["drifted-1", "drifted-2", "drifted-3"])

    stages = []
    result = _restore(
        env,
        backup,
        encryption_key=PASSPHRASE,
        safety_backup_dir=env["backups"],
        safety_passphrase="safety-passphrase",
        on_stage=stages.append,
    )
    assert stages == ["gate", "preflight", "safety_backup", "restore", "done"]
    assert _names(env["db"]) == ["alpha", "beta"]

    safety = Path(env["backups"]) / result["safetyBackup"]
    assert safety.exists() and safety.read_bytes()[:8] == b"DSMENC1\0"

    # The safety backup really contains the pre-restore (drifted) state.
    listed = asyncio.run(env["adapter"].list_backups())
    safety_info = next(b for b in listed if b.name == result["safetyBackup"])
    manager = env["manager"]
    dry = manager.dry_run_restore(safety_info, encryption_key="safety-passphrase")
    assert dry["ok"] is True

    log = audit.audit_log_path().read_text()
    entry = json.loads(log.strip().splitlines()[-1])
    assert entry["outcome"] == "completed"
    assert entry["safetyBackup"] == result["safetyBackup"]
    assert PASSPHRASE not in log and "safety-passphrase" not in log


def test_wrong_passphrase_fails_preflight_before_any_change(env):
    _enable(env)
    backup = env["make_backup"](
        compression="gzip", encryption=True, encryptionKey=PASSPHRASE
    )
    _make_db(env["db"], ["changed"])
    with pytest.raises(RestoreRefused, match="Pre-flight"):
        _restore(env, backup, encryption_key="not-the-passphrase")
    assert _names(env["db"]) == ["changed"]
    assert not list(Path(env["backups"]).glob("*.enc.safety*"))
    assert audit.read_audit()[-1]["stage"] == "preflight"


def test_safety_backup_requires_its_own_passphrase(env):
    _enable(env)
    backup = env["make_backup"]()
    _make_db(env["db"], ["changed"])
    with pytest.raises(RestoreRefused, match="safety backup"):
        _restore(env, backup, safety_backup_dir=env["backups"], safety_passphrase="")
    assert _names(env["db"]) == ["changed"]


def test_tampered_backup_is_rejected_by_checksum(env):
    _enable(env)
    backup = env["make_backup"](compression="gzip")
    path = Path(backup.path)
    data = bytearray(path.read_bytes())
    data[-5] ^= 0xFF
    path.write_bytes(bytes(data))
    _make_db(env["db"], ["changed"])
    with pytest.raises(RestoreRefused, match="Pre-flight"):
        _restore(env, backup)
    assert _names(env["db"]) == ["changed"]


def test_backup_records_dump_and_live_sizes(env):
    backup = env["make_backup"](compression="gzip")
    meta = backup.metadata
    assert meta["dumpSize"] == env["db"].stat().st_size
    assert isinstance(meta["sourceStorageBytes"], int) and meta["sourceStorageBytes"] > 0
    assert backup.size < meta["dumpSize"]
    listed = asyncio.run(env["adapter"].list_backups())
    assert listed[0].metadata["dumpSize"] == meta["dumpSize"]
    assert listed[0].metadata["sourceStorageBytes"] == meta["sourceStorageBytes"]


def test_pipeline_roundtrip_matches_local_format(tmp_path):
    source = tmp_path / "dump.bin"
    payload = b"pipeline-roundtrip\n" * 5000
    source.write_bytes(payload)
    options = BackupOptions(
        connectionId="c",
        connectionName="pipe",
        databaseType="sqlite",
        backupPath=str(source),
        compression="zstd",
        encryption=True,
        encryptionKey=PASSPHRASE,
    )
    prepared = prepare_payload(options)
    try:
        assert prepared.encrypted and prepared.filename.endswith(".zst.enc")
        assert prepared.path.read_bytes()[:8] == b"DSMENC1\0"
        assert prepared.sha256 == sha256_file(prepared.path)
        assert prepared.dump_size == len(payload) and prepared.size < len(payload)
        with pytest.raises(ValueError, match="passphrase"):
            unpack_payload(prepared.path, prepared.metadata, None)
        out = unpack_payload(prepared.path, prepared.metadata, PASSPHRASE)
        assert out.read_bytes() == payload
        out.unlink()
    finally:
        prepared.cleanup()


def test_pipeline_can_refuse_plaintext_for_remote_destinations(tmp_path):
    source = tmp_path / "dump.bin"
    source.write_bytes(b"x")
    options = BackupOptions(
        connectionId="c",
        connectionName="pipe",
        databaseType="sqlite",
        backupPath=str(source),
    )
    with pytest.raises(ValueError, match="requires DSMENC1"):
        prepare_payload(options, require_encryption=True)


def test_audit_strips_secret_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", tmp_path / "audit.log")
    audit.write_audit(
        "x.y", "completed", note="ok", passphrase="hunter2", nested={"apiToken": "t", "k": 1}
    )
    text = audit.audit_log_path().read_text()
    assert "hunter2" not in text and "apiToken" not in text
    assert json.loads(text)["nested"] == {"k": 1}
    # 0o600 is applied only where the OS stores Unix mode bits.
    if os.name != "nt":
        assert (audit.audit_log_path().stat().st_mode & 0o777) == 0o600


def test_scratch_restore_leaves_production_untouched(env):
    _enable(env)
    backup = env["make_backup"](compression="gzip")
    _make_db(env["db"], ["drifted"])
    before = env["db"].read_bytes()
    result = asyncio.run(
        env["manager"].scratch_restore(
            env["adapter"], backup, env["cfg"], confirmation="SCRATCH"
        )
    )
    assert env["db"].read_bytes() == before
    assert _names(env["db"]) == ["drifted"]
    scratch = Path(result["scratchDatabase"])
    assert scratch.is_file() and scratch.resolve() != env["db"].resolve()
    assert _names(scratch) == ["alpha", "beta"]
    entry = audit.read_audit()[-1]
    assert entry["action"] == "backup.scratch_restore"
    assert entry["outcome"] == "completed"
    assert entry["scratchDatabase"] == str(scratch)


def test_scratch_restore_refuses_the_production_name(env):
    _enable(env)
    backup = env["make_backup"]()
    with pytest.raises(RestoreRefused, match="SCRATCH"):
        asyncio.run(
            env["manager"].scratch_restore(
                env["adapter"], backup, env["cfg"], confirmation="prod.db"
            )
        )
    assert _names(env["db"]) == ["alpha", "beta"]
    assert list(env["tmp"].glob("*.scratch-*")) == []


def test_backups_in_the_same_second_never_overwrite_each_other(env):
    first = env["make_backup"](compression="gzip")
    second = env["make_backup"](compression="gzip")
    third = env["make_backup"](compression="gzip")
    paths = {first.path, second.path, third.path}
    assert len(paths) == 3
    assert all(Path(p).exists() for p in paths)
    assert len(asyncio.run(env["adapter"].list_backups())) == 3
