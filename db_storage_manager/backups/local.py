"""
Local file system backup adapter
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime
import uuid

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..config import BACKUP_DIR
from ..native import gzip_compress_file, gzip_decompress_file, sha256_file


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

        processed_path = source_path

        # Apply compression if requested (Rust/PyO3 when available)
        if options.compression == "gzip":
            compressed_path = self.base_path / f"{original_filename}.gz"
            gzip_compress_file(source_path, compressed_path)
            processed_path = compressed_path
            final_filename += ".gz"
        else:
            # Copy to backup directory
            final_path = self.base_path / final_filename
            shutil.copy2(source_path, final_path)
            processed_path = final_path

        # Apply encryption if requested (placeholder - implement with cryptography)
        if options.encryption and options.encryptionKey:
            # TODO: Implement encryption
            final_filename += ".enc"

        size = processed_path.stat().st_size
        checksum = sha256_file(processed_path)
        created_at = datetime.now()
        metadata = {
            "id": backup_id,
            "compression": options.compression or "none",
            "encryption": options.encryption or False,
            "databaseType": options.databaseType,
            "connectionId": options.connectionId,
            "connectionName": options.connectionName,
            "sha256": checksum,
            "createdAt": created_at.isoformat(),
        }
        self._write_meta(processed_path, metadata)

        return BackupInfo(
            id=backup_id,
            name=final_filename,
            path=str(processed_path),
            size=size,
            createdAt=created_at,
            status="completed",
            metadata={
                "compression": metadata["compression"],
                "encryption": metadata["encryption"],
                "databaseType": options.databaseType,
                "connectionId": options.connectionId,
                "sha256": checksum,
            },
        )

    async def restore_backup(self, backup_info: BackupInfo) -> str:
        """Restore a local backup"""
        backup_path = Path(backup_info.path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Handle decompression (Rust/PyO3 when available)
        if backup_info.metadata.get("compression") == "gzip":
            import tempfile

            temp_path = Path(tempfile.mktemp(suffix=".backup"))
            gzip_decompress_file(backup_path, temp_path)
            return str(temp_path)

        return str(backup_path)

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
            compression = stored.get("compression")
            if compression is None:
                compression = "gzip" if backup_file.suffix == ".gz" else "none"
            encryption = stored.get("encryption")
            if encryption is None:
                encryption = backup_file.suffix == ".enc"

            metadata: Dict[str, Any] = {
                "compression": compression,
                "encryption": bool(encryption),
            }
            for key in ("databaseType", "connectionId", "connectionName", "sha256"):
                if key in stored and stored[key] is not None:
                    metadata[key] = stored[key]

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
