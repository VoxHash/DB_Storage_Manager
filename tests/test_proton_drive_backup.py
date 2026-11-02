"""Proton Drive backup adapter tests (rclone boundary mocked; no live network)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

from db_storage_manager.backups.base import BackupOptions
from db_storage_manager.backups.local import sanitize_backup_basename
from db_storage_manager.backups.manager import BackupManager
from db_storage_manager.backups.protondrive import (
    ProtonDriveBackupAdapter,
    ProtonDriveNotConfiguredError,
    RcloneResult,
    configuration_status,
    load_protondrive_dotenv,
    resolve_proton_drive_config,
    resolve_rclone_binary,
    rclone_remote_configured,
    save_proton_drive_credentials,
    write_ephemeral_protondrive_rclone_config,
)
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.native import ENCRYPTION_SCHEME, sha256_file
from db_storage_manager.security.store import SecureStore

# Mirrors GUI failure: pooler / SSH labels with em dash, spaces, parentheses, slash.
_UNSAFE_CONNECTION_NAME = (
    "redacted-pooler — Database Url "
    "(aws-0-us-east-1.pooler.supabase.com/postgres)"
)
_UNSAFE_SSH_MYSQL_NAME = "vps/prod — SSH tunnel (mysql)"


def _strip_rclone_global_flags(argv: List[str]) -> List[str]:
    """Drop leading ``--config PATH`` pairs so command dispatch sees the verb."""
    i = 0
    while i < len(argv):
        if argv[i] == "--config" and i + 1 < len(argv):
            i += 2
            continue
        break
    return argv[i:]


def _rclone_verb(argv: List[str]) -> Optional[str]:
    cmd = _strip_rclone_global_flags(argv)
    return cmd[0] if cmd else None


class FakeRcloneRunner:
    """In-memory rclone double that stores uploaded objects."""

    def __init__(
        self, *, remotes: Optional[List[str]] = None, fail_listremotes: bool = False
    ):
        self.remotes = remotes if remotes is not None else ["protondrive"]
        self.fail_listremotes = fail_listremotes
        self.objects: Dict[str, bytes] = {}
        self.calls: List[List[str]] = []
        self.envs: List[Optional[Dict[str, str]]] = []
        self.config_paths_seen: List[str] = []

    def run(
        self,
        args: Sequence[str],
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> RcloneResult:
        argv = list(args)
        self.calls.append(argv)
        self.envs.append(env)
        # Capture --config path before stripping for dispatch
        for idx, token in enumerate(argv):
            if token == "--config" and idx + 1 < len(argv):
                self.config_paths_seen.append(argv[idx + 1])
        cmd_argv = _strip_rclone_global_flags(argv)
        cmd = cmd_argv[0] if cmd_argv else ""

        if cmd == "obscure":
            # Deterministic stand-in for rclone obscure (not real crypto).
            raw = cmd_argv[1] if len(cmd_argv) > 1 else ""
            fake = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
            return RcloneResult(0, fake + "\n", "", argv)

        if cmd == "listremotes":
            if self.fail_listremotes:
                return RcloneResult(1, "", "listremotes failed", argv)
            out = "\n".join(f"{r}:" for r in self.remotes) + "\n"
            return RcloneResult(0, out, "", argv)

        if cmd in ("mkdir", "lsd"):
            return RcloneResult(0, "", "", argv)

        if cmd == "copyto" and len(cmd_argv) >= 3:
            src, dst = cmd_argv[1], cmd_argv[2]
            if os.path.isfile(src):
                self.objects[dst] = Path(src).read_bytes()
                return RcloneResult(0, "", "", argv)
            if src in self.objects:
                Path(dst).write_bytes(self.objects[src])
                return RcloneResult(0, "", "", argv)
            return RcloneResult(1, "", f"object not found: {src}", argv)

        if cmd == "lsjson":
            remote_prefix = cmd_argv[1] if len(cmd_argv) > 1 else ""
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
            remote = cmd_argv[1]
            if remote not in self.objects:
                return RcloneResult(1, "", "not found", argv)
            return RcloneResult(0, self.objects[remote].decode("utf-8"), "", argv)

        if cmd == "deletefile":
            remote = cmd_argv[1]
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
    cfg = resolve_proton_drive_config(
        {}, settings={"proton_drive": {}}, load_env_file=False
    )
    assert cfg["username"] == "user@proton.me"
    assert cfg["password"] == "secret"
    assert cfg["path"] == "lab-backups"
    assert cfg["prefer_encryption"] is True


def test_configuration_status_missing_rclone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_RCLONE", raising=False)
    monkeypatch.delenv("RCLONE_BIN", raising=False)
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive._RCLONE_FALLBACK_PATHS",
        (tmp_path / "no-rclone",),
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.shutil.which",
        lambda _name: None,
    )
    status = configuration_status(
        {
            "rclone_bin": "rclone-not-installed-xyz",
            "username": None,
            "password": None,
            "remote": "protondrive",
        },
        runner=FakeRcloneRunner(remotes=[]),
        settings={"proton_drive": {}},
    )
    assert status["configured"] is False
    assert status["error"]


def test_configuration_status_with_creds_and_fake_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_bin = tmp_path / "rclone"
    fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive._RCLONE_FALLBACK_PATHS",
        (fake_bin,),
    )
    runner = FakeRcloneRunner(remotes=["protondrive"])
    status = configuration_status(
        {
            "rclone_bin": str(fake_bin),
            "username": "user@proton.me",
            "password": "secret",
            "remote": "protondrive",
        },
        runner=runner,
        settings={"proton_drive": {}},
    )
    assert status["configured"] is True
    assert status["has_credentials"] is True


def test_resolve_rclone_binary_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_bin = tmp_path / "rclone"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive._RCLONE_FALLBACK_PATHS",
        (fake_bin,),
    )
    monkeypatch.delenv("DSM_PROTONDRIVE_RCLONE", raising=False)
    monkeypatch.delenv("RCLONE_BIN", raising=False)
    found = resolve_rclone_binary("rclone")
    assert found == str(fake_bin.resolve())


def test_configuration_status_from_securestore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_bin = tmp_path / "rclone"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.shutil.which",
        lambda _name: str(fake_bin),
    )
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)

    settings = {
        "proton_drive": {
            "remote": "protondrive",
            "path": "db-storage-manager-backups",
            "rclone_bin": str(fake_bin),
            "prefer_encryption": True,
            "username": "secure@proton.me",
            "password": "secure-secret",
        }
    }
    runner = FakeRcloneRunner(remotes=[])
    status = configuration_status(
        {},
        runner=runner,
        settings=settings,
    )
    assert status["configured"] is True
    assert status["has_credentials"] is True
    assert status["remote_in_rclone_config"] is False


def test_save_proton_drive_credentials_roundtrip(isolated_secure_store):
    store, _data_dir = isolated_secure_store
    assert isinstance(store, SecureStore)

    redacted = save_proton_drive_credentials(
        username="ui@proton.me",
        password="ui-password-value",
        otp_secret_key="OTPSECRET",
        prefer_encryption=True,
    )
    assert redacted.get("username") == "***"
    assert redacted.get("password") == "***"
    assert "ui-password-value" not in str(redacted)

    stored = SecureStore().get_settings().get("proton_drive") or {}
    cfg = resolve_proton_drive_config(
        {},
        settings={"proton_drive": stored},
        load_env_file=False,
    )
    assert cfg["username"] == "ui@proton.me"
    assert cfg["password"] == "ui-password-value"
    assert cfg["otp_secret_key"] == "OTPSECRET"


def test_load_protondrive_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env.protondrive.local"
    env_file.write_text(
        "DSM_PROTONDRIVE_USERNAME=dotenv@proton.me\n"
        "DSM_PROTONDRIVE_PASSWORD=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)
    loaded = load_protondrive_dotenv(override=True)
    assert loaded is not None
    assert os.environ.get("DSM_PROTONDRIVE_USERNAME") == "dotenv@proton.me"
    cfg = resolve_proton_drive_config(
        {}, settings={"proton_drive": {}}, load_env_file=False
    )
    assert cfg["username"] == "dotenv@proton.me"
    assert cfg["password"] == "dotenv-secret"


def test_rclone_remote_configured_parses_section_only(tmp_path: Path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(
        "[other]\ntype = s3\n\n[protondrive]\ntype = protondrive\n"
        "username = should-not-be-read-by-assert\n",
        encoding="utf-8",
    )
    assert rclone_remote_configured("protondrive", config_path=conf) is True
    assert rclone_remote_configured("missing", config_path=conf) is False


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
    source_dump: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DSM_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("DSM_PROTONDRIVE_PASSWORD", raising=False)
    monkeypatch.delenv("RCLONE_PROTONDRIVE_USERNAME", raising=False)
    monkeypatch.delenv("RCLONE_PROTONDRIVE_PASSWORD", raising=False)
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.load_protondrive_dotenv",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive._RCLONE_FALLBACK_PATHS",
        (tmp_path / "missing-rclone",),
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.rclone_remote_configured",
        lambda *_a, **_k: False,
    )
    runner = FakeRcloneRunner(remotes=[])
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "definitely-missing-rclone-bin",
            "prefer_encryption": False,
            "username": None,
            "password": None,
        },
        runner=runner,
        settings={"proton_drive": {}},
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


def test_create_backup_sanitizes_unsafe_connection_name(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: Proton+encrypt must not Errno 2 when connectionName has /."""
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
        connectionId="c-supabase",
        connectionName=_UNSAFE_CONNECTION_NAME,
        databaseType="postgres",
        backupPath=str(source_dump),
        compression="none",
        encryption=True,
        encryptionKey="proton-unsafe-name-key",
        adapterType="protondrive",
    )
    info = asyncio.run(adapter.create_backup(options))

    assert info.status == "completed"
    assert "/" not in info.name
    assert "\\" not in info.name
    assert "—" not in info.name
    assert " " not in info.name
    assert Path(info.name).name == info.name
    assert info.name.endswith(".backup.enc")
    assert info.metadata["encryption"] is True
    assert info.metadata["encryptionScheme"] == ENCRYPTION_SCHEME
    safe_stem = sanitize_backup_basename(_UNSAFE_CONNECTION_NAME)
    assert info.name.startswith(safe_stem)
    # Original display name preserved in uploaded meta sidecar (not the filename)
    listed = asyncio.run(adapter.list_backups())
    assert listed[0].metadata.get("connectionName") == _UNSAFE_CONNECTION_NAME
    # rclone copyto target leaf must be a single path segment
    copy_calls = [
        _strip_rclone_global_flags(c)
        for c in runner.calls
        if _rclone_verb(c) == "copyto"
    ]
    assert copy_calls
    for call in copy_calls:
        remote_leaf = call[2].rsplit("/", 1)[-1]
        assert "/" not in remote_leaf
        assert "—" not in remote_leaf


def test_create_backup_sanitizes_ssh_mysql_connection_name(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: SSH/MySQL labels with / must not nest under /tmp/dsm-proton-*."""
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
        connectionId="c-mysql",
        connectionName=_UNSAFE_SSH_MYSQL_NAME,
        databaseType="mysql",
        backupPath=str(source_dump),
        compression="none",
        encryption=True,
        encryptionKey="ssh-mysql-proton-key",
        adapterType="protondrive",
    )
    info = asyncio.run(adapter.create_backup(options))
    assert info.status == "completed"
    assert "/" not in info.name
    assert info.name.endswith(".backup.enc")
    listed = asyncio.run(adapter.list_backups())
    assert listed[0].metadata.get("connectionName") == _UNSAFE_SSH_MYSQL_NAME


def test_manager_proton_encrypt_unsafe_connection_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: BackupManager dump → Proton adapter with unsafe name (mocked rclone)."""
    payload = b"-- postgres dump\nSELECT 1;\n"

    class _StringPathDumpConnection:
        def __init__(self, data: bytes):
            self._data = data

        async def create_backup(self, path: str):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(self._data)
            return path

        async def restore_backup(self, path: str):
            return None

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
    manager = BackupManager()
    conn = _StringPathDumpConnection(payload)

    async def _acquire(_config):
        return conn

    async def _release(_connection):
        return None

    monkeypatch.setattr(
        "db_storage_manager.backups.manager.DatabaseConnectionFactory.acquire",
        _acquire,
    )
    monkeypatch.setattr(
        "db_storage_manager.backups.manager.DatabaseConnectionFactory.release",
        _release,
    )

    cfg = ConnectionConfig(
        id="c1",
        name=_UNSAFE_CONNECTION_NAME,
        type="postgres",
        host="127.0.0.1",
        port=5432,
        database="postgres",
        username="u",
        password="p",
    )
    info = asyncio.run(
        manager.create_backup(
            adapter,
            cfg,
            {
                "compression": "none",
                "encryption": True,
                "encryptionKey": "manager-proton-unsafe-key",
                "adapterType": "protondrive",
            },
        )
    )
    assert info.status == "completed"
    assert "/" not in info.name
    assert info.name.endswith(".backup.enc")
    assert info.metadata.get("encryption") is True
    assert any(k.endswith(info.name) for k in runner.objects)


def test_ephemeral_rclone_config_when_creds_present_and_conf_missing(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: env/SecureStore creds must drive rclone via temp --config.

    Without a ``[protondrive]`` section, plain ``rclone mkdir protondrive:…``
    fails with "didn't find section in config file". Adapter must obscure
    secrets, write mode-600 temp conf, pass ``--config``, and clean up.
    """
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.rclone_remote_configured",
        lambda *_a, **_k: False,
    )
    runner = FakeRcloneRunner(remotes=[])
    spaced_folder = "DB Storage Manager"
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "/usr/bin/env",
            "remote": "protondrive",
            "path": spaced_folder,
            "prefer_encryption": True,
            "username": "user@proton.me",
            "password": "plain-secret",
            "otp_secret_key": "JBSWY3DPEHPK3PXP",
            "2fa": None,
        },
        runner=runner,
    )

    options = BackupOptions(
        connectionId="c1",
        connectionName="labdb",
        databaseType="sqlite",
        backupPath=str(source_dump),
        compression="none",
        encryption=True,
        encryptionKey="ephemeral-conf-key",
        adapterType="protondrive",
    )
    info = asyncio.run(adapter.create_backup(options))
    assert info.status == "completed"

    obscure_calls = [c for c in runner.calls if _rclone_verb(c) == "obscure"]
    assert obscure_calls, "expected rclone obscure for password/otp"
    # plaintext must not appear in non-obscure argv (temp conf holds obscured form)
    mkdir_calls = [
        _strip_rclone_global_flags(c)
        for c in runner.calls
        if _rclone_verb(c) == "mkdir"
    ]
    assert mkdir_calls
    mkdir_target = mkdir_calls[0][1]
    assert mkdir_target == f"protondrive:{spaced_folder}"
    assert " " in mkdir_target  # single argv element preserves spaces

    ops_with_config = [
        c
        for c in runner.calls
        if _rclone_verb(c) in ("mkdir", "copyto") and "--config" in c
    ]
    assert ops_with_config, "mkdir/copyto must pass --config when conf missing"
    for call in ops_with_config:
        conf_idx = call.index("--config")
        conf_path = Path(call[conf_idx + 1])
        # Temp config is cleaned up after the with-block
        assert not conf_path.exists()

    # Env must not carry plaintext backend password
    for env in runner.envs:
        if env is None:
            continue
        assert "RCLONE_PROTONDRIVE_PASSWORD" not in env
        assert "RCLONE_PROTONDRIVE_USERNAME" not in env

    assert runner.config_paths_seen
    assert info.path.startswith(f"protondrive:{spaced_folder}/")


def test_write_ephemeral_protondrive_rclone_config_mode_600(tmp_path: Path):
    conf = write_ephemeral_protondrive_rclone_config(
        "protondrive",
        username="user@proton.me",
        password_obscured="obscured-pass-value",
        otp_secret_key_obscured="obscured-otp",
        two_fa="123456",
    )
    try:
        mode = conf.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600
        text = conf.read_text(encoding="utf-8")
        assert "[protondrive]" in text
        assert "type = protondrive" in text
        assert "username = user@proton.me" in text
        assert "password = obscured-pass-value" in text
        assert "otp_secret_key = obscured-otp" in text
        assert "2fa = 123456" in text
        assert "plain-secret" not in text
    finally:
        conf.unlink(missing_ok=True)


def test_existing_rclone_conf_skips_ephemeral_config(
    source_dump: Path, monkeypatch: pytest.MonkeyPatch
):
    """When ``[protondrive]`` already exists, do not inject --config / obscure."""
    monkeypatch.setattr(
        "db_storage_manager.backups.protondrive.rclone_remote_configured",
        lambda *_a, **_k: True,
    )
    runner = FakeRcloneRunner(remotes=["protondrive"])
    adapter = ProtonDriveBackupAdapter(
        {
            "rclone_bin": "/usr/bin/env",
            "remote": "protondrive",
            "path": "db-storage-manager-backups",
            "prefer_encryption": True,
            "username": "user@proton.me",
            "password": "plain-secret",
        },
        runner=runner,
    )
    options = BackupOptions(
        connectionId="c1",
        connectionName="labdb",
        databaseType="sqlite",
        backupPath=str(source_dump),
        compression="none",
        encryption=True,
        encryptionKey="existing-conf-key",
        adapterType="protondrive",
    )
    info = asyncio.run(adapter.create_backup(options))
    assert info.status == "completed"
    assert not any(_rclone_verb(c) == "obscure" for c in runner.calls)
    assert not any("--config" in c for c in runner.calls if _rclone_verb(c) == "mkdir")
