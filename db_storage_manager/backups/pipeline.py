"""Shared backup payload pipeline for remote adapters (S3, Google Drive, ...).

Create:  dump -> optional compression (gzip / zstd) -> optional DSMENC1
         encryption -> SHA-256 of the stored bytes.
Restore: stored bytes -> decrypt (needs the passphrase) -> decompress.

Local and Proton Drive keep their own equivalent code paths; this module keeps
the newer remote adapters on exactly the same on-disk format so every
destination can be verified, dry-run and restored the same way.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..native import (
    ENCRYPTION_SCHEME,
    decrypt_file,
    encrypt_file,
    gzip_compress_file,
    gzip_decompress_file,
    sha256_file,
    zstd_compress_file,
    zstd_decompress_file,
)
from .base import BackupInfo, BackupOptions
from .local import sanitize_backup_basename


@dataclass
class PreparedPayload:
    """Result of :func:`prepare_payload` (``work_dir`` is removed by ``cleanup``)."""

    path: Path
    filename: str
    backup_id: str
    compression: str
    encrypted: bool
    sha256: str
    size: int
    dump_size: int
    created_at: datetime
    work_dir: Path
    metadata: Dict[str, Any] = field(default_factory=dict)

    def cleanup(self) -> None:
        shutil.rmtree(self.work_dir, ignore_errors=True)


def prepare_payload(
    options: BackupOptions,
    *,
    require_encryption: bool = False,
    prefix: str = "dsm-payload-",
) -> PreparedPayload:
    """Compress / encrypt ``options.backupPath`` into a temp work directory.

    ``require_encryption`` refuses plaintext uploads (cloud opsec default).
    """
    source = Path(options.backupPath)
    if not source.exists():
        raise FileNotFoundError(
            f"Backup source file not found: {options.backupPath}"
        )

    encrypt = bool(options.encryption)
    if require_encryption and not encrypt:
        raise ValueError(
            "This destination stores backups off-machine and requires DSMENC1 "
            "encryption: pass encryption=True with an encryption passphrase."
        )
    if encrypt and not options.encryptionKey:
        raise ValueError("encryption=True requires encryptionKey (passphrase)")

    backup_id = str(uuid.uuid4())
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{sanitize_backup_basename(options.connectionName)}_{stamp}.backup"
    work_dir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        dump_size = source.stat().st_size
        compression = (options.compression or "none").lower()
        filename = base
        if compression == "gzip":
            filename = f"{base}.gz"
            current = work_dir / filename
            gzip_compress_file(source, current)
        elif compression == "zstd":
            filename = f"{base}.zst"
            current = work_dir / filename
            zstd_compress_file(source, current)
        else:
            compression = "none"
            current = work_dir / filename
            shutil.copy2(source, current)

        if encrypt:
            enc = work_dir / f"{filename}.enc"
            encrypt_file(current, enc, str(options.encryptionKey))
            current.unlink(missing_ok=True)
            current = enc
            filename = f"{filename}.enc"

        checksum = sha256_file(current)
        created = datetime.now()
        size = current.stat().st_size
        metadata: Dict[str, Any] = {
            "id": backup_id,
            "name": filename,
            "compression": compression,
            "encryption": encrypt,
            "encryptionScheme": ENCRYPTION_SCHEME if encrypt else None,
            "databaseType": options.databaseType,
            "connectionId": options.connectionId,
            "connectionName": options.connectionName,
            "sha256": checksum,
            "createdAt": created.isoformat(),
            "size": size,
            "dumpSize": dump_size,
        }
        for key in ("sourceStorageBytes",):
            value = (options.metadata or {}).get(key)
            if isinstance(value, int):
                metadata[key] = value
        return PreparedPayload(
            path=current,
            filename=filename,
            backup_id=backup_id,
            compression=compression,
            encrypted=encrypt,
            sha256=checksum,
            size=size,
            dump_size=dump_size,
            created_at=created,
            work_dir=work_dir,
            metadata=metadata,
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def unpack_payload(
    stored: Path,
    metadata: Mapping[str, Any],
    passphrase: Optional[str] = None,
) -> Path:
    """Decrypt + decompress a stored backup into a new temp file.

    The input file is left untouched. The caller owns (and must delete) the
    returned path.
    """
    temps: List[Path] = []
    try:
        current = Path(stored)
        if metadata.get("encryption"):
            if not passphrase:
                raise ValueError(
                    "Encrypted backup requires an encryption passphrase"
                )
            fd, name = tempfile.mkstemp(suffix=".dec.backup")
            os.close(fd)
            decrypted = Path(name)
            temps.append(decrypted)
            decrypt_file(current, decrypted, str(passphrase))
            current = decrypted

        compression = str(metadata.get("compression") or "none").lower()
        if compression in ("gzip", "zstd"):
            fd, name = tempfile.mkstemp(suffix=".backup")
            os.close(fd)
            out = Path(name)
            temps.append(out)
            if compression == "gzip":
                gzip_decompress_file(current, out)
            else:
                zstd_decompress_file(current, out)
            current = out

        if current == Path(stored):
            # Plain, uncompressed object: hand back a private copy so the
            # caller can always delete the result.
            fd, name = tempfile.mkstemp(suffix=".backup")
            os.close(fd)
            copy = Path(name)
            shutil.copyfile(current, copy)
            return copy

        # Keep only the final file; drop intermediates.
        for temp in temps:
            if temp != current:
                temp.unlink(missing_ok=True)
        return current
    except Exception:
        for temp in temps:
            temp.unlink(missing_ok=True)
        raise


def checksum_result(backup_info: BackupInfo, local_path: Path) -> Dict[str, Any]:
    """Compare a downloaded object with the SHA-256 stored in its metadata."""
    expected = (backup_info.metadata or {}).get("sha256")
    actual = sha256_file(local_path)
    size = Path(local_path).stat().st_size
    base = {
        "path": backup_info.path,
        "expected": expected,
        "actual": actual,
        "size": size,
    }
    if not expected:
        return {
            **base,
            "ok": False,
            "status": "missing_checksum",
            "error": "No stored SHA-256 checksum in backup metadata",
        }
    matched = expected == actual
    return {
        **base,
        "ok": matched,
        "status": "pass" if matched else "fail",
        "error": None if matched else "SHA-256 mismatch",
    }
