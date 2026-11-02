"""Regression: BackupManager must accept string OR dict dump results.

MySQL/Postgres historically returned a bare path string from ``create_backup``.
Indexing that string with ``["path"]`` raised:
``TypeError: string indices must be integers, not 'str'`` (GUI: Backup failed).
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from db_storage_manager.backups.local import LocalBackupAdapter, sanitize_backup_basename
from db_storage_manager.backups.manager import BackupManager, backup_path_from_result
from db_storage_manager.db.base import ConnectionConfig
from db_storage_manager.native import ENCRYPTION_SCHEME, decrypt_file, sha256_file


# Mirrors the GUI failure: long Supabase pooler label with em dash, spaces,
# parentheses, and a slash in the host path segment.
_UNSAFE_SUPABASE_NAME = (
    "redacted-pooler — Database Url "
    "(aws-0-us-east-1.pooler.supabase.com/postgres)"
)


def test_backup_path_from_result_accepts_str_and_dict(tmp_path: Path):
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")
    assert backup_path_from_result(str(dump)) == str(dump)
    assert backup_path_from_result(dump) == str(dump)
    assert backup_path_from_result({"path": str(dump), "size": 7}) == str(dump)


def test_backup_path_from_result_rejects_bad_shapes():
    with pytest.raises(ValueError, match="missing 'path'"):
        backup_path_from_result({"size": 1})
    with pytest.raises(TypeError, match="path str or dict"):
        backup_path_from_result(42)  # type: ignore[arg-type]


class _StringPathDumpConnection:
    """Stand-in for MySQL/Postgres drivers that return a bare path string."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self.connected = True

    async def create_backup(self, backup_path: str):
        path = Path(backup_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._payload)
        return str(path)  # historical MySQL return shape


class _DictPathDumpConnection:
    """Stand-in for SQLite/Mongo/Redis drivers that return ``{path, size}``."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self.connected = True

    async def create_backup(self, backup_path: str):
        path = Path(backup_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._payload)
        return {"path": str(path), "size": path.stat().st_size}


def _cfg(name: str = "ssh-mysql-demo") -> ConnectionConfig:
    return ConnectionConfig(
        id="conn-backup-path-1",
        name=name,
        type="mysql",
        host="127.0.0.1",
        port=3306,
        database="demo",
        username="u",
        password="p",
    )


def test_manager_local_encrypt_with_string_dump_result(tmp_path: Path, monkeypatch):
    """GUI path: SSH/MySQL dump returns str → Local + DSMENC1 must succeed."""
    payload = b"-- MySQL dump\nCREATE TABLE t(id INT);\n"
    conn = _StringPathDumpConnection(payload)
    adapter = LocalBackupAdapter(base_path=tmp_path / "backups")
    manager = BackupManager()

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

    passphrase = "regression-test-passphrase"
    info = asyncio.run(
        manager.create_backup(
            adapter,
            _cfg(),
            {
                "compression": "none",
                "encryption": True,
                "encryptionKey": passphrase,
                "adapterType": "local",
            },
        )
    )

    assert Path(info.path).name.endswith(".backup.enc")
    assert info.metadata.get("encryption") is True
    assert info.metadata.get("encryptionScheme") == ENCRYPTION_SCHEME
    assert Path(info.path).read_bytes()[:8] == b"DSMENC1\0"
    assert info.metadata.get("sha256") == sha256_file(info.path)

    dec = tmp_path / "roundtrip.sql"
    decrypt_file(info.path, dec, passphrase)
    assert dec.read_bytes() == payload


def test_manager_local_plain_with_string_and_dict_dump(tmp_path: Path, monkeypatch):
    """Local backup without encryption works for string and dict dump shapes."""
    manager = BackupManager()

    async def _release(_connection):
        return None

    monkeypatch.setattr(
        "db_storage_manager.backups.manager.DatabaseConnectionFactory.release",
        _release,
    )

    for label, factory in (
        ("string", lambda: _StringPathDumpConnection(b"sql-string\n")),
        ("dict", lambda: _DictPathDumpConnection(b"sql-dict\n")),
    ):
        adapter = LocalBackupAdapter(base_path=tmp_path / f"backups-{label}")
        conn = factory()

        async def _acquire(_config, _conn=conn):
            return _conn

        monkeypatch.setattr(
            "db_storage_manager.backups.manager.DatabaseConnectionFactory.acquire",
            _acquire,
        )
        info = asyncio.run(
            manager.create_backup(
                adapter,
                _cfg(name=f"demo-{label}"),
                {"compression": "none", "encryption": False, "adapterType": "local"},
            )
        )
        assert Path(info.path).exists()
        assert info.metadata.get("encryption") is False
        assert Path(info.path).name.endswith(".backup")


def test_manager_sqlite_local_encrypt_and_plain(tmp_path: Path):
    """Non-SSH SQLite through real BackupManager + Local adapter (dict dump)."""
    db_path = tmp_path / "live.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items(name) VALUES ('alpha')")
        conn.commit()
    finally:
        conn.close()

    cfg = ConnectionConfig(
        id="sqlite-1",
        name="local-sqlite",
        type="sqlite",
        database=str(db_path),
    )
    adapter = LocalBackupAdapter(base_path=tmp_path / "backups")
    manager = BackupManager()

    plain = asyncio.run(
        manager.create_backup(
            adapter,
            cfg,
            {"compression": "none", "encryption": False, "adapterType": "local"},
        )
    )
    assert Path(plain.path).exists()
    assert plain.metadata.get("encryption") is False

    enc = asyncio.run(
        manager.create_backup(
            adapter,
            cfg,
            {
                "compression": "none",
                "encryption": True,
                "encryptionKey": "sqlite-enc-key",
                "adapterType": "local",
            },
        )
    )
    assert Path(enc.path).name.endswith(".enc")
    assert enc.metadata.get("encryption") is True
    assert Path(enc.path).read_bytes()[:8] == b"DSMENC1\0"


def test_sanitize_backup_basename_strips_path_separators():
    safe = sanitize_backup_basename(_UNSAFE_SUPABASE_NAME)
    assert "/" not in safe
    assert "\\" not in safe
    assert "—" not in safe
    assert "(" not in safe
    assert " " not in safe
    assert Path(safe).name == safe  # single path segment
    # Distinct originals stay distinct after sanitization
    other = sanitize_backup_basename(
        "other — Database Url (aws-0-eu.pooler.supabase.com/postgres)"
    )
    assert safe != other


def test_manager_local_encrypt_unsafe_supabase_connection_name(
    tmp_path: Path, monkeypatch
):
    """Regression: Local+encrypt must not Errno 2 on long pooler labels with /."""
    payload = b"-- postgres dump\nSELECT 1;\n"
    conn = _StringPathDumpConnection(payload)
    # Intentionally missing parent until adapter mkdir — mirrors fresh config dir
    backups_root = tmp_path / "config" / "db-storage-manager" / "backups"
    adapter = LocalBackupAdapter(base_path=backups_root)
    manager = BackupManager()

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

    passphrase = "supabase-pooler-enc-key"
    info = asyncio.run(
        manager.create_backup(
            adapter,
            _cfg(name=_UNSAFE_SUPABASE_NAME),
            {
                "compression": "none",
                "encryption": True,
                "encryptionKey": passphrase,
                "adapterType": "local",
            },
        )
    )

    out = Path(info.path)
    assert out.exists()
    assert out.parent == backups_root
    assert "/" not in out.name
    assert "—" not in out.name
    assert out.name.endswith(".backup.enc")
    assert info.metadata.get("encryption") is True
    assert info.metadata.get("encryptionScheme") == ENCRYPTION_SCHEME
    assert out.read_bytes()[:8] == b"DSMENC1\0"
    # Original display name preserved in sidecar metadata, not the filename
    listed = asyncio.run(adapter.list_backups())
    assert listed[0].metadata.get("connectionName") == _UNSAFE_SUPABASE_NAME

    dec = tmp_path / "roundtrip.sql"
    decrypt_file(info.path, dec, passphrase)
    assert dec.read_bytes() == payload
