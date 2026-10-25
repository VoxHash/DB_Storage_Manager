"""Proton Drive backup adapter tests (rclone boundary mocked; no live network)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

from db_storage_manager.backups.base import BackupOptions
from db_storage_manager.backups.manager import BackupManager
from db_storage_manager.backups.protondrive import (
    ProtonDriveBackupAdapter,
    ProtonDriveNotConfiguredError,
    RcloneResult,
    configuration_status,
    resolve_proton_drive_config,
)
from db_storage_manager.native import ENCRYPTION_SCHEME, sha256_file


class FakeRcloneRunner:
    """In-memory rclone double that stores uploaded objects."""

    def __init__(
        self, *, remotes: Optional[List[str]] = None, fail_listremotes: bool = False
    ):
        self.remotes = remotes if remotes is not None else ["protondrive"]
        self.fail_listremotes = fail_listremotes
        self.objects: Dict[str, bytes] = {}
        self.calls: List[List[str]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> RcloneResult:
        argv = list(args)
        self.calls.append(argv)
        cmd = argv[0] if argv else ""

        if cmd == "listremotes":
            if self.fail_listremotes:
                return RcloneResult(1, "", "listremotes failed", argv)
            out = "\n".join(f"{r}:" for r in self.remotes) + "\n"
            return RcloneResult(0, out, "", argv)

        if cmd in ("mkdir", "lsd"):
            return RcloneResult(0, "", "", argv)

        if cmd == "copyto" and len(argv) >= 3:
            src, dst = argv[1], argv[2]
            if os.path.isfile(src):
                self.objects[dst] = Path(src).read_bytes()
                return RcloneResult(0, "", "", argv)
            if src in self.objects:
                Path(dst).write_bytes(self.objects[src])
                return RcloneResult(0, "", "", argv)
            return RcloneResult(1, "", f"object not found: {src}", argv)

        if cmd == "lsjson":
            remote_prefix = argv[1] if len(argv) > 1 else ""
            entries = []
            for key, data in self.objects.items():
                if remote_prefix and not key.startswith(remote_prefix):
                    continue
                name = key.split("/")[-1]
                if name.endswith(".meta.json"):
                    continue
                entries.append(
                    {
                        "Name": name,
                        "Path": name,
                        "Size": len(data),
                        "ModTime": "2026-10-25T12:00:00Z",
                    }
                )
            return RcloneResult(0, json.dumps(entries), "", argv)

        if cmd == "cat":
            remote = argv[1]
            if remote not in self.objects:
                return RcloneResult(1, "", "not found", argv)
            return RcloneResult(0, self.objects[remote].decode("utf-8"), "", argv)

        if cmd == "deletefile":
            remote = argv[1]
            self.objects.pop(remote, None)
            return RcloneResult(0, "", "", argv)

        return RcloneResult(1, "", f"unexpected rclone args: {argv}", argv)


@pytest.fixture
def source_dump(tmp_path: Path) -> Path:
    path = tmp_path / "dump.sqlite"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    return path


def test_resolve_config_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSM_PROTONDRIVE_USERNAME", "user@proton.me")
    monkeypatch.setenv("DSM_PROTONDRIVE_PASSWORD", "secret")
    monkeypatch.setenv("DSM_PROTONDRIVE_PATH", "lab-backups")
    cfg = resolve_proton_drive_config({}, settings={"proton_drive": {}})
    assert cfg["username"] == "user@proton.me"
    assert cfg["password"] == "secret"
    assert cfg["path"] == "lab-backups"
    assert cfg["prefer_encryption"] is True


def test_configuration_status_missing_rclone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)
    status = configuration_status(
        {
            "rclone_bin": "rclone-not-installed-xyz",
            "username": None,
            "password": None,
            "remote": "protondrive",
        },
        runner=FakeRcloneRunner(remotes=[]),
    )
    assert status["configured"] is False
    assert status["error"]


def test_configuration_status_with_creds_and_fake_runner():
    runner = FakeRcloneRunner(remotes=["protondrive"])
    status = configuration_status(
        {
            "rclone_bin": "/usr/bin/env",
            "username": "user@proton.me",
            "password": "secret",
            "remote": "protondrive",
        },
        runner=runner,
    )
    assert status["configured"] is True
    assert status["has_credentials"] is True


def test_create_list_verify_delete_with_encryption(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSM_PROTONDRIVE_USERNAME", "user@proton.me")
    monkeypatch.setenv("DSM_PROTONDRIVE_PASSWORD", "secret")
    runner = FakeRcloneRunner(remotes=["protondrive"])
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "/usr/bin/env",
            "remote": "protondrive",
            "path": "db-storage-manager-backups",
            "prefer_encryption": True,
            "username": "user@proton.me",
            "password": "secret",
        },
        runner=runner,
    )

    options = BackupOptions(
        connectionId="c1",
        connectionName="labdb",
        databaseType="sqlite",
        backupPath=str(source_dump),
        compression="zstd",
        encryption=True,
        encryptionKey="test-passphrase-proton",
        adapterType="protondrive",
    )
    info = asyncio.run(adapter.create_backup(options))
    assert info.status == "completed"
    assert info.name.endswith(".zst.enc")
    assert info.metadata["encryption"] is True
    assert info.metadata["encryptionScheme"] == ENCRYPTION_SCHEME
    assert info.metadata["sha256"]
    assert info.metadata["destination"] == "protondrive"

    assert any(k.endswith(info.name) for k in runner.objects)
    assert any(k.endswith(f"{info.name}.meta.json") for k in runner.objects)

    listed = asyncio.run(adapter.list_backups())
    assert len(listed) == 1
    assert listed[0].name == info.name
    assert listed[0].metadata.get("sha256") == info.metadata["sha256"]

    verify = adapter.verify_remote_checksum(listed[0])
    assert verify["ok"] is True
    assert verify["status"] == "pass"

    local = asyncio.run(adapter.restore_backup(listed[0]))
    assert Path(local).exists()
    assert sha256_file(local) == info.metadata["sha256"]
    Path(local).unlink(missing_ok=True)

    asyncio.run(adapter.delete_backup(listed[0].id))
    assert asyncio.run(adapter.list_backups()) == []


def test_prefer_encryption_requires_key(source_dump: Path):
    runner = FakeRcloneRunner()
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "/usr/bin/env",
            "username": "u",
            "password": "p",
            "prefer_encryption": True,
        },
        runner=runner,
    )
    options = BackupOptions(
        connectionId="c1",
        connectionName="labdb",
        databaseType="sqlite",
        backupPath=str(source_dump),
        encryption=False,
        encryptionKey=None,
    )
    with pytest.raises(ValueError, match="prefer DSMENC1 encryption"):
        asyncio.run(adapter.create_backup(options))


def test_clear_error_when_not_configured(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)
    runner = FakeRcloneRunner(remotes=[])
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "definitely-missing-rclone-bin",
            "prefer_encryption": False,
        },
        runner=runner,
    )
    options = BackupOptions(
        connectionId="c1",
        connectionName="labdb",
        databaseType="sqlite",
        backupPath=str(source_dump),
        encryption=False,
    )
    with pytest.raises(ProtonDriveNotConfiguredError):
        asyncio.run(adapter.create_backup(options))


def test_manager_registers_protondrive_adapter():
    manager = BackupManager()
    adapter = manager.get_adapter(
        "protondrive",
        {
            "username": "u",
            "password": "p",
            "rclone_bin": "/usr/bin/env",
        },
    )
    assert isinstance(adapter, ProtonDriveBackupAdapter)
    again = manager.get_adapter("protondrive")
    assert again is adapter
