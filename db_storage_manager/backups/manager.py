"""
Backup manager for coordinating backup operations
"""

from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
import tempfile

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..native import sha256_file, sha256_files_parallel


class BackupManager:
    """Manages backup operations across different adapters"""

    def __init__(self):
        self.adapters: Dict[str, BackupAdapter] = {}

    def register_adapter(self, adapter_type: str, adapter: BackupAdapter) -> None:
        """Register a backup adapter"""
        self.adapters[adapter_type] = adapter

    def get_adapter(
        self, adapter_type: str, config: Optional[Dict[str, Any]] = None
    ) -> Optional[BackupAdapter]:
        """Get a backup adapter by type"""
        if adapter_type in self.adapters:
            return self.adapters[adapter_type]

        # Create adapter dynamically if not registered
        if adapter_type == "local":
            from .local import LocalBackupAdapter

            adapter = LocalBackupAdapter()
            self.register_adapter("local", adapter)
            return adapter
        elif adapter_type == "s3" and config:
            from .s3 import S3BackupAdapter

            adapter = S3BackupAdapter(config)
            self.register_adapter("s3", adapter)
            return adapter
        elif adapter_type == "googledrive" and config:
            from .googledrive import GoogleDriveBackupAdapter

            adapter = GoogleDriveBackupAdapter(config)
            self.register_adapter("googledrive", adapter)
            return adapter

        return None

    async def create_backup(
        self,
        adapter: BackupAdapter,
        connection_config: ConnectionConfig,
        options: Optional[Dict[str, Any]] = None,
    ) -> BackupInfo:
        """Create a backup for a database connection"""
        db_connection = await DatabaseConnectionFactory.acquire(connection_config)

        try:
            # Create temporary backup file
            temp_dir = Path(tempfile.gettempdir())
            temp_backup = (
                temp_dir
                / f"{connection_config.name}_{__import__('time').time()}.tmpbackup"
            )

            # Create backup using database connection
            backup_result = await db_connection.create_backup(str(temp_backup))

            # Prepare backup options
            backup_options = BackupOptions(
                connectionId=connection_config.id,
                connectionName=connection_config.name,
                databaseType=connection_config.type,
                backupPath=backup_result["path"],
                compression=options.get("compression") if options else None,
                encryption=options.get("encryption", False) if options else False,
                encryptionKey=options.get("encryptionKey") if options else None,
                metadata=connection_config.__dict__,
                adapterType=options.get("adapterType") if options else None,
                adapterConfig=options.get("adapterConfig") if options else None,
            )

            # Upload to adapter
            backup_info = await adapter.create_backup(backup_options)

            # Clean up temporary file if not local adapter
            if not isinstance(adapter, type(self.get_adapter("local"))):
                temp_backup.unlink(missing_ok=True)

            return backup_info
        finally:
            await DatabaseConnectionFactory.release(db_connection)

    async def restore_backup(
        self,
        adapter: BackupAdapter,
        backup_info: BackupInfo,
        connection_config: ConnectionConfig,
        encryption_key: Optional[str] = None,
    ) -> None:
        """Restore a backup to a database connection"""
        # Download backup from adapter if needed
        local_backup_path = await adapter.restore_backup(
            backup_info, encryption_key=encryption_key
        )

        try:
            db_connection = await DatabaseConnectionFactory.acquire(connection_config)

            try:
                # Restore backup
                await db_connection.restore_backup(local_backup_path)
            finally:
                await DatabaseConnectionFactory.release(db_connection)
        finally:
            # Clean up temporary file if it was downloaded
            if local_backup_path != backup_info.path:
                Path(local_backup_path).unlink(missing_ok=True)

    async def create_batch_backups(
        self,
        connections: List[ConnectionConfig],
        adapter: BackupAdapter,
        options: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Create backups for multiple connections"""
        results = []

        for connection in connections:
            try:
                if on_progress:
                    on_progress(
                        {"connectionId": connection.id, "status": "in_progress"}
                    )

                backup_info = await self.create_backup(adapter, connection, options)

                result = {
                    "connectionId": connection.id,
                    "status": "completed",
                    "backupInfo": backup_info,
                }
                results.append(result)

                if on_progress:
                    on_progress({"connectionId": connection.id, "status": "completed"})
            except Exception as e:
                result = {
                    "connectionId": connection.id,
                    "status": "failed",
                    "error": str(e),
                }
                results.append(result)

                if on_progress:
                    on_progress(
                        {
                            "connectionId": connection.id,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

        return results

    def verify_backup_checksum(self, backup_info: BackupInfo) -> Dict[str, Any]:
        """Verify a backup file against its stored SHA-256 metadata."""
        path = Path(backup_info.path)
        if not path.exists():
            return {
                "ok": False,
                "status": "not_found",
                "path": str(path),
                "expected": None,
                "actual": None,
                "error": "Backup file not found",
            }

        expected = (backup_info.metadata or {}).get("sha256")
        actual = sha256_file(path)
        size = path.stat().st_size
        if not expected:
            return {
                "ok": False,
                "status": "missing_checksum",
                "path": str(path),
                "expected": None,
                "actual": actual,
                "size": size,
                "error": "No stored SHA-256 checksum in backup metadata",
            }
        matched = expected == actual
        return {
            "ok": matched,
            "status": "pass" if matched else "fail",
            "path": str(path),
            "expected": expected,
            "actual": actual,
            "size": size,
            "error": None if matched else "SHA-256 mismatch",
        }

    def verify_backups_parallel(
        self, backups: List[BackupInfo]
    ) -> List[Dict[str, Any]]:
        """Verify many backup checksums using parallel native hashing when available."""
        paths = [b.path for b in backups]
        digests = dict(sha256_files_parallel(paths))
        results = []
        for backup in backups:
            expected = (backup.metadata or {}).get("sha256")
            actual = digests.get(backup.path) or None
            if not Path(backup.path).exists():
                results.append(
                    {
                        "ok": False,
                        "status": "not_found",
                        "path": backup.path,
                        "id": backup.id,
                        "expected": expected,
                        "actual": None,
                        "error": "Backup file not found",
                    }
                )
                continue
            if not expected:
                results.append(
                    {
                        "ok": False,
                        "status": "missing_checksum",
                        "path": backup.path,
                        "id": backup.id,
                        "expected": None,
                        "actual": actual,
                        "error": "No stored SHA-256 checksum in backup metadata",
                    }
                )
                continue
            matched = bool(actual) and expected == actual
            results.append(
                {
                    "ok": matched,
                    "status": "pass" if matched else "fail",
                    "path": backup.path,
                    "id": backup.id,
                    "expected": expected,
                    "actual": actual,
                    "error": None if matched else "SHA-256 mismatch",
                }
            )
        return results

    def dry_run_restore(
        self,
        backup_info: BackupInfo,
        encryption_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate a backup can be restored without writing to a live database.

        Steps: SHA-256 verify → optional decrypt (DSMENC1) → optional
        gzip/zstd decompress to a temp file → payload readability checks
        (SQLite header + PRAGMA integrity_check when the payload is SQLite).
        """
        import os
        import sqlite3
        import tempfile

        from ..native import (
            decrypt_file,
            gzip_decompress_file,
            zstd_decompress_file,
        )

        checksum = self.verify_backup_checksum(backup_info)
        if not checksum.get("ok"):
            return {
                "ok": False,
                "status": checksum.get("status", "fail"),
                "stage": "checksum",
                "checksum": checksum,
                "error": checksum.get("error") or "Checksum verification failed",
            }

        source = Path(backup_info.path)
        metadata = backup_info.metadata or {}
        passphrase = encryption_key or metadata.get("encryptionKey")
        temps: List[Path] = []
        try:
            current = source
            if metadata.get("encryption"):
                if not passphrase:
                    return {
                        "ok": False,
                        "status": "fail",
                        "stage": "decrypt",
                        "checksum": checksum,
                        "error": "Encrypted backup requires encryption_key",
                    }
                fd, temp_name = tempfile.mkstemp(suffix=".dryrun.dec")
                os.close(fd)
                dec_path = Path(temp_name)
                temps.append(dec_path)
                decrypt_file(current, dec_path, str(passphrase))
                current = dec_path

            compression = str(metadata.get("compression") or "none").lower()
            if compression in ("gzip", "zstd"):
                fd, temp_name = tempfile.mkstemp(suffix=".dryrun.backup")
                os.close(fd)
                temp_path = Path(temp_name)
                temps.append(temp_path)
                if compression == "gzip":
                    gzip_decompress_file(current, temp_path)
                else:
                    zstd_decompress_file(current, temp_path)
                payload = temp_path
            else:
                payload = current

            if not payload.exists() or payload.stat().st_size == 0:
                return {
                    "ok": False,
                    "status": "fail",
                    "stage": "payload",
                    "checksum": checksum,
                    "error": "Backup payload is missing or empty",
                }

            payload_size = payload.stat().st_size
            db_type = str(metadata.get("databaseType") or "").lower()
            with open(payload, "rb") as handle:
                magic = handle.read(16)
            is_sqlite = magic.startswith(b"SQLite format 3") or db_type == "sqlite"

            integrity = None
            if is_sqlite:
                if not magic.startswith(b"SQLite format 3"):
                    return {
                        "ok": False,
                        "status": "fail",
                        "stage": "header",
                        "checksum": checksum,
                        "payload_size": payload_size,
                        "error": "Payload is not a valid SQLite database header",
                    }
                uri = f"file:{payload.resolve().as_posix()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True)
                try:
                    row = conn.execute("PRAGMA integrity_check").fetchone()
                    integrity = row[0] if row else "failed"
                finally:
                    conn.close()
                if integrity != "ok":
                    return {
                        "ok": False,
                        "status": "fail",
                        "stage": "integrity_check",
                        "checksum": checksum,
                        "payload_size": payload_size,
                        "integrity": integrity,
                        "error": f"SQLite integrity_check failed: {integrity}",
                    }

            return {
                "ok": True,
                "status": "pass",
                "stage": "complete",
                "checksum": checksum,
                "payload_size": payload_size,
                "integrity": integrity,
                "databaseType": metadata.get("databaseType"),
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "fail",
                "stage": "dry_run",
                "checksum": checksum,
                "error": str(exc),
            }
        finally:
            for temp_path in temps:
                temp_path.unlink(missing_ok=True)
