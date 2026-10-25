"""
Local file system backup adapter
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..config import BACKUP_DIR
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


def meta_path_for(backup_path: Path) -> Path:
    """Sidecar JSON path that stores SHA-256 and backup metadata."""
    return Path(str(backup_path) + ".meta.json")


class LocalBackupAdapter(BackupAdapter):
    """Local file system backup adapter"""

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or BACKUP_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _write_meta(self, backup_path: Path, metadata: Dict[str, Any]) -> None:
        sidecar = meta_path_for(backup_path)
        payload = dict(metadata)
        payload["name"] = backup_path.name
        payload["path"] = str(backup_path)
        with open(sidecar, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)

    def _read_meta(self, backup_path: Path) -> Optional[Dict[str, Any]]:
        sidecar = meta_path_for(backup_path)
        if not sidecar.exists():
            return None
        try:
            with open(sidecar, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _infer_compression(self, backup_file: Path, stored: Dict[str, Any]) -> str:
        compression = stored.get("compression")
        if compression is not None:
            return str(compression)
        name = backup_file.name
        # Strip .enc suffix for compression detection
        if name.endswith(".enc"):
            name = name[: -len(".enc")]
        if name.endswith(".gz"):
            return "gzip"
        if name.endswith(".zst"):
            return "zstd"
        return "none"

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Create a local backup"""
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = f"{options.connectionName}_{timestamp}.backup"
        final_filename = original_filename

        source_path = Path(options.backupPath)
        if not source_path.exists():
            raise FileNotFoundError(
                f"Backup source file not found: {options.backupPath}"
            )

        intermediate: Optional[Path] = None
        processed_path: Path

        compression = (options.compression or "none").lower()
        if compression == "gzip":
            compressed_path = self.base_path / f"{original_filename}.gz"
            gzip_compress_file(source_path, compressed_path)
            processed_path = compressed_path
            final_filename = f"{original_filename}.gz"
            intermediate = compressed_path
        elif compression == "zstd":
            compressed_path = self.base_path / f"{original_filename}.zst"
            zstd_compress_file(source_path, compressed_path)
            processed_path = compressed_path
            final_filename = f"{original_filename}.zst"
            intermediate = compressed_path
        else:
            compression = "none"
            final_path = self.base_path / final_filename
            shutil.copy2(source_path, final_path)
            processed_path = final_path

        encrypted = False
        if options.encryption:
            if not options.encryptionKey:
                raise ValueError(
                    "encryption=True requires encryptionKey (passphrase)"
                )
            enc_path = self.base_path / f"{final_filename}.enc"
            encrypt_file(processed_path, enc_path, options.encryptionKey)
            if intermediate is not None and intermediate.exists():
                intermediate.unlink(missing_ok=True)
                meta_path_for(intermediate).unlink(missing_ok=True)
            elif processed_path != source_path and processed_path.exists():
                # Unencrypted copy in backup dir — replace with ciphertext
                if processed_path != enc_path:
                    processed_path.unlink(missing_ok=True)
            processed_path = enc_path
            final_filename = f"{final_filename}.enc"
            encrypted = True

        size = processed_path.stat().st_size
        checksum = sha256_file(processed_path)
        created_at = datetime.now()
        metadata = {
            "id": backup_id,
            "compression": compression,
            "encryption": encrypted,
            "encryptionScheme": ENCRYPTION_SCHEME if encrypted else None,
            "databaseType": options.databaseType,
            "connectionId": options.connectionId,
            "connectionName": options.connectionName,
            "sha256": checksum,
            "createdAt": created_at.isoformat(),
        }
        # Never persist the passphrase
        self._write_meta(processed_path, metadata)

        info_meta: Dict[str, Any] = {
            "compression": compression,
            "encryption": encrypted,
            "databaseType": options.databaseType,
            "connectionId": options.connectionId,
            "sha256": checksum,
        }
        if encrypted:
            info_meta["encryptionScheme"] = ENCRYPTION_SCHEME

        return BackupInfo(
            id=backup_id,
            name=final_filename,
            path=str(processed_path),
            size=size,
            createdAt=created_at,
            status="completed",
            metadata=info_meta,
        )

    async def restore_backup(
        self,
        backup_info: BackupInfo,
        encryption_key: Optional[str] = None,
    ) -> str:
        """Restore a local backup; returns a local payload path (may be temp)."""
        backup_path = Path(backup_info.path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        metadata = backup_info.metadata or {}
        passphrase = encryption_key or metadata.get("encryptionKey")
        temps: List[Path] = []
        current = backup_path

        try:
            if metadata.get("encryption"):
                if not passphrase:
                    raise ValueError(
                        "Encrypted backup requires encryption_key / encryptionKey"
                    )
                fd, temp_name = tempfile.mkstemp(suffix=".dec.backup")
                os.close(fd)
                dec_path = Path(temp_name)
                temps.append(dec_path)
                decrypt_file(current, dec_path, str(passphrase))
                current = dec_path

            compression = str(metadata.get("compression") or "none").lower()
            if compression == "gzip":
                fd, temp_name = tempfile.mkstemp(suffix=".backup")
                os.close(fd)
                out_path = Path(temp_name)
                gzip_decompress_file(current, out_path)
                if current in temps:
                    current.unlink(missing_ok=True)
                    temps.remove(current)
                temps.append(out_path)
                return str(out_path)
            if compression == "zstd":
                fd, temp_name = tempfile.mkstemp(suffix=".backup")
                os.close(fd)
                out_path = Path(temp_name)
                zstd_decompress_file(current, out_path)
                if current in temps:
                    current.unlink(missing_ok=True)
                    temps.remove(current)
                temps.append(out_path)
                return str(out_path)

            # Decrypted plaintext temp or original path
            if current in temps:
                # Leave temp for caller; do not delete in finally
                temps.remove(current)
                return str(current)
            return str(current)
        except Exception:
            for path in temps:
                path.unlink(missing_ok=True)
            raise

    async def list_backups(self) -> list[BackupInfo]:
        """List all local backups"""
        backups = []

        for backup_file in sorted(self.base_path.glob("*.backup*")):
            if not backup_file.is_file():
                continue
            if backup_file.name.endswith(".meta.json"):
                continue

            stored = self._read_meta(backup_file) or {}
            backup_id = str(stored.get("id") or uuid.uuid4())
            compression = self._infer_compression(backup_file, stored)
            encryption = stored.get("encryption")
            if encryption is None:
                encryption = backup_file.name.endswith(".enc")

            metadata: Dict[str, Any] = {
                "compression": compression,
                "encryption": bool(encryption),
            }
            for key in (
                "databaseType",
                "connectionId",
                "connectionName",
                "sha256",
                "encryptionScheme",
            ):
                if key in stored and stored[key] is not None:
                    metadata[key] = stored[key]
            if metadata["encryption"] and "encryptionScheme" not in metadata:
                metadata["encryptionScheme"] = ENCRYPTION_SCHEME

            created_at = datetime.fromtimestamp(backup_file.stat().st_mtime)
            created_raw = stored.get("createdAt")
            if isinstance(created_raw, str):
                try:
                    created_at = datetime.fromisoformat(created_raw)
                except ValueError:
                    pass

            backups.append(
                BackupInfo(
                    id=backup_id,
                    name=backup_file.name,
                    path=str(backup_file),
                    size=backup_file.stat().st_size,
                    createdAt=created_at,
                    status="completed",
                    metadata=metadata,
                )
            )

        return backups

    async def delete_backup(self, backup_id: str) -> None:
        """Delete a local backup"""
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)

        if backup:
            path = Path(backup.path)
            path.unlink(missing_ok=True)
            meta_path_for(path).unlink(missing_ok=True)
        else:
            raise FileNotFoundError(f"Backup not found: {backup_id}")

    async def validate_options(self, options: BackupOptions) -> bool:
        """Validate backup options"""
        return self.base_path.exists() and self.base_path.is_dir()
