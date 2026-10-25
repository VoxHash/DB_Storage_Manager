"""zstd compression and DSMENC1 backup encryption (real crypto, no mocks)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from db_storage_manager.backups.base import BackupOptions
from db_storage_manager.backups.local import LocalBackupAdapter
from db_storage_manager.backups.manager import BackupManager
from db_storage_manager.native import (
    ENCRYPTION_FORMAT,
    ENCRYPTION_SCHEME,
    decrypt_file,
    encrypt_file,
    sha256_file,
    zstd_compress_file,
    zstd_decompress_file,
)


def _sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items(name) VALUES ('alpha'), ('beta')")
        conn.commit()
    finally:
        conn.close()


def test_zstd_roundtrip(tmp_path: Path):
    src = tmp_path / "payload.bin"
    zst = tmp_path / "payload.bin.zst"
    out = tmp_path / "payload.out"
    payload = b"db-storage-manager-zstd-test\n" * 4000
    src.write_bytes(payload)

    size = zstd_compress_file(src, zst)
    assert size > 0
    assert zst.exists()
    assert zst.stat().st_size < src.stat().st_size

    written = zstd_decompress_file(zst, out)
    assert written == len(payload)
    assert out.read_bytes() == payload


def test_encrypt_decrypt_roundtrip(tmp_path: Path):
    src = tmp_path / "plain.bin"
    enc = tmp_path / "plain.bin.enc"
    out = tmp_path / "plain.out"
    payload = b"secret-backup-bytes\n" * 3000
    src.write_bytes(payload)

    size = encrypt_file(src, enc, "test-passphrase-please")
    assert size > 0
    assert enc.read_bytes()[:8] == b"DSMENC1\0"
    assert enc.read_bytes() != payload

    written = decrypt_file(enc, out, "test-passphrase-please")
    assert written == len(payload)
    assert out.read_bytes() == payload

    with pytest.raises(ValueError):
        decrypt_file(enc, tmp_path / "bad.out", "wrong-passphrase")


def test_encryption_constants():
    assert ENCRYPTION_FORMAT == "DSMENC1"
    assert ENCRYPTION_SCHEME == "aes-256-gcm-pbkdf2"


@pytest.fixture
def local_adapter(tmp_path: Path) -> LocalBackupAdapter:
    return LocalBackupAdapter(base_path=tmp_path / "backups")


def test_local_zstd_create_restore_dry_run(
    local_adapter: LocalBackupAdapter, tmp_path: Path
):
    source = tmp_path / "live.db"
    _sqlite_db(source)
    before = source.read_bytes()

    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="zstd-demo",
                databaseType="sqlite",
                backupPath=str(source),
                compression="zstd",
            )
        )
    )
    assert Path(info.path).name.endswith(".zst")
    assert info.metadata.get("compression") == "zstd"
    assert info.metadata.get("sha256") == sha256_file(info.path)

    result = BackupManager().dry_run_restore(info)
    assert result["ok"] is True
    assert result["integrity"] == "ok"
    assert source.read_bytes() == before

    restored = asyncio.run(local_adapter.restore_backup(info))
    assert Path(restored).read_bytes() == before
    Path(restored).unlink(missing_ok=True)


def test_local_encrypted_create_restore_dry_run(
    local_adapter: LocalBackupAdapter, tmp_path: Path
):
    source = tmp_path / "secure.db"
    _sqlite_db(source)
    before = source.read_bytes()
    passphrase = "unit-test-backup-key"

    info = asyncio.run(
        local_adapter.create_backup(
            BackupOptions(
                connectionId="c1",
                connectionName="enc-demo",
                databaseType="sqlite",
                backupPath=str(source),
                compression="zstd",
                encryption=True,
                encryptionKey=passphrase,
            )
        )
    )
    assert Path(info.path).name.endswith(".zst.enc")
    assert info.metadata.get("encryption") is True
    assert info.metadata.get("encryptionScheme") == ENCRYPTION_SCHEME
    assert info.metadata.get("compression") == "zstd"
    assert Path(info.path).read_bytes()[:8] == b"DSMENC1\0"

    listed = asyncio.run(local_adapter.list_backups())
    assert len(listed) == 1
    assert listed[0].metadata.get("encryption") is True
    assert "encryptionKey" not in (listed[0].metadata or {})

    fail = BackupManager().dry_run_restore(info)
    assert fail["ok"] is False
    assert fail["stage"] == "decrypt"

    result = BackupManager().dry_run_restore(info, encryption_key=passphrase)
    assert result["ok"] is True
    assert result["integrity"] == "ok"
    assert source.read_bytes() == before

    restored = asyncio.run(
        local_adapter.restore_backup(info, encryption_key=passphrase)
    )
    assert Path(restored).read_bytes() == before
    Path(restored).unlink(missing_ok=True)


def test_encryption_requires_key(local_adapter: LocalBackupAdapter, tmp_path: Path):
    source = tmp_path / "need-key.db"
    _sqlite_db(source)
    with pytest.raises(ValueError, match="encryptionKey"):
        asyncio.run(
            local_adapter.create_backup(
                BackupOptions(
                    connectionId="c1",
                    connectionName="no-key",
                    databaseType="sqlite",
                    backupPath=str(source),
                    encryption=True,
                    encryptionKey=None,
                )
            )
        )
