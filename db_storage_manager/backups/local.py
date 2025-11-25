"""
Local file system backup adapter
"""

import gzip
import shutil
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import uuid

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..config import BACKUP_DIR


class LocalBackupAdapter(BackupAdapter):
    """Local file system backup adapter"""

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or BACKUP_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Create a local backup"""
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = f"{options.connectionName}_{timestamp}.backup"
        final_filename = original_filename

        source_path = Path(options.backupPath)
        if not source_path.exists():
            raise FileNotFoundError(f"Backup source file not found: {options.backupPath}")

        processed_path = source_path

        # Apply compression if requested
        if options.compression == "gzip":
            compressed_path = self.base_path / f"{original_filename}.gz"
            with open(source_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
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

        return BackupInfo(
            id=backup_id,
            name=final_filename,
            path=str(processed_path),
            size=size,
            createdAt=datetime.now(),
            status="completed",
            metadata={
                "compression": options.compression or "none",
                "encryption": options.encryption or False,
                "databaseType": options.databaseType,
                "connectionId": options.connectionId,
            },
        )

    async def restore_backup(self, backup_info: BackupInfo) -> str:
        """Restore a local backup"""
        backup_path = Path(backup_info.path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Handle decompression
        if backup_info.metadata.get("compression") == "gzip":
            import tempfile
            temp_path = Path(tempfile.mktemp(suffix=".backup"))
            with gzip.open(backup_path, "rb") as f_in:
                with open(temp_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            return str(temp_path)

        return str(backup_path)

    async def list_backups(self) -> list[BackupInfo]:
        """List all local backups"""
        backups = []

        for backup_file in self.base_path.glob("*.backup*"):
            if backup_file.is_file():
                backup_id = str(uuid.uuid4())  # Generate ID from filename or metadata
                backups.append(BackupInfo(
                    id=backup_id,
                    name=backup_file.name,
                    path=str(backup_file),
                    size=backup_file.stat().st_size,
                    createdAt=datetime.fromtimestamp(backup_file.stat().st_mtime),
                    status="completed",
                    metadata={
                        "compression": "gzip" if backup_file.suffix == ".gz" else "none",
                        "encryption": backup_file.suffix == ".enc",
                    },
                ))

        return backups

    async def delete_backup(self, backup_id: str) -> None:
        """Delete a local backup"""
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)

        if backup:
            Path(backup.path).unlink()
        else:
            raise FileNotFoundError(f"Backup not found: {backup_id}")

    async def validate_options(self, options: BackupOptions) -> bool:
        """Validate backup options"""
        return self.base_path.exists() and self.base_path.is_dir()

