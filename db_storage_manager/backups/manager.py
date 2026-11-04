"""
Backup manager for coordinating backup operations
"""

from typing import Any, Dict, List, Optional, Callable, Union
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading

from ..audit import write_audit

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..native import sha256_file, sha256_files_parallel


def backup_path_from_result(backup_result: Union[str, Path, Dict[str, Any]]) -> str:
    """Normalize ``DatabaseConnection.create_backup`` return values to a file path.

    Drivers historically returned either a bare path string (MySQL, Postgres,
    SQL Server, …) or a dict with a ``path`` key (SQLite, Mongo, Redis). The
    manager must accept both; indexing a string with ``["path"]`` raises
    ``TypeError: string indices must be integers, not 'str'``.
    """
    if isinstance(backup_result, (str, Path)):
        path = str(backup_result)
        if not path:
            raise ValueError("create_backup returned an empty path")
        return path
    if isinstance(backup_result, dict):
        path = backup_result.get("path")
        if path is None or path == "":
            raise ValueError("create_backup result missing 'path'")
        return str(path)
    raise TypeError(
        "create_backup must return a path str or dict with 'path', "
        f"got {type(backup_result).__name__}"
    )


# Destinations that store backups off this machine. Their ``restore_backup``
# returns the stored object (still encrypted / compressed); Local returns an
# unpacked payload. Cloud destinations must always be encrypted.
REMOTE_DESTINATIONS = {
    "protondrive": "protondrive",
    "proton_drive": "protondrive",
    "proton": "protondrive",
    "s3": "s3",
    "googledrive": "googledrive",
}
ENCRYPTED_ADAPTERS = frozenset({"protondrive", "s3", "googledrive"})

# Engine names that identify the same dump format.
_DB_TYPE_FAMILY = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "supabase": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mssql": "sqlserver",
    "sqlserver": "sqlserver",
    "mongodb": "mongodb",
    "mongo": "mongodb",
}


def _db_family(name: Any) -> str:
    key = str(name or "").strip().lower()
    return _DB_TYPE_FAMILY.get(key, key)


class RestoreRefused(RuntimeError):
    """A full restore was stopped before any change was made to the target."""


class BackupManager:
    """Manages backup operations across different adapters"""

    def __init__(self):
        self.adapters: Dict[str, BackupAdapter] = {}
        # GUI jobs, scheduled jobs and the API may resolve adapters concurrently.
        self._adapter_lock = threading.RLock()

    def register_adapter(self, adapter_type: str, adapter: BackupAdapter) -> None:
        """Register a backup adapter"""
        with self._adapter_lock:
            self.adapters[adapter_type] = adapter

    def get_adapter(
        self, adapter_type: str, config: Optional[Dict[str, Any]] = None
    ) -> Optional[BackupAdapter]:
        """Get a backup adapter by type"""
        with self._adapter_lock:
            return self._get_adapter_locked(adapter_type, config)

    def _get_adapter_locked(
        self, adapter_type: str, config: Optional[Dict[str, Any]] = None
    ) -> Optional[BackupAdapter]:
        if adapter_type in self.adapters:
            return self.adapters[adapter_type]

        # Create adapter dynamically if not registered
        if adapter_type == "local":
            from .local import LocalBackupAdapter

            adapter = LocalBackupAdapter()
            self.register_adapter("local", adapter)
            return adapter
        elif adapter_type == "s3":
            from .s3 import S3BackupAdapter, resolve_s3_config

            resolved = dict(config or {})
            if not resolved.get("bucket"):
                resolved = {**resolve_s3_config(), **resolved}
            if not resolved.get("bucket"):
                return None
            adapter = S3BackupAdapter(resolved)
            self.register_adapter("s3", adapter)
            return adapter
        elif adapter_type == "googledrive" and config:
            from .googledrive import GoogleDriveBackupAdapter

            adapter = GoogleDriveBackupAdapter(config)
            self.register_adapter("googledrive", adapter)
            return adapter
        elif adapter_type in ("protondrive", "proton_drive", "proton"):
            from .protondrive import ProtonDriveBackupAdapter

            adapter = ProtonDriveBackupAdapter(config or {})
            self.register_adapter("protondrive", adapter)
            return adapter

        return None

    def _effective_connection_config(
        self, connection_config: ConnectionConfig
    ) -> ConnectionConfig:
        """Rewrite host/port through a local SSH forward when ssh_config is enabled."""
        ssh = connection_config.ssh_config or {}
        if not ssh.get("enabled"):
            return connection_config
        from ..db.session import ensure_tunnel_for_connection

        kwargs = ensure_tunnel_for_connection(dict(connection_config.__dict__))
        return ConnectionConfig(**kwargs)

    async def create_backup(
        self,
        adapter: BackupAdapter,
        connection_config: ConnectionConfig,
        options: Optional[Dict[str, Any]] = None,
    ) -> BackupInfo:
        """Create a backup for a database connection"""
        effective = self._effective_connection_config(connection_config)
        db_connection = await DatabaseConnectionFactory.acquire(effective)

        try:
            # Create temporary backup file (sanitize name: no path separators)
            from .local import sanitize_backup_basename

            temp_dir = Path(tempfile.gettempdir())
            safe_stem = sanitize_backup_basename(connection_config.name)
            temp_backup = (
                temp_dir
                / f"{safe_stem}_{__import__('time').time()}.tmpbackup"
            )
            temp_backup.parent.mkdir(parents=True, exist_ok=True)

            # Live relation size at backup time (best effort): lets the UI show
            # live size vs dump size vs stored size for the same moment.
            source_storage_bytes = await self._live_storage_bytes(db_connection)

            # Create backup using database connection
            backup_result = await db_connection.create_backup(str(temp_backup))
            dump_path = backup_path_from_result(backup_result)

            # Prepare backup options
            backup_options = BackupOptions(
                connectionId=connection_config.id,
                connectionName=connection_config.name,
                databaseType=connection_config.type,
                backupPath=dump_path,
                compression=options.get("compression") if options else None,
                encryption=options.get("encryption", False) if options else False,
                encryptionKey=options.get("encryptionKey") if options else None,
                metadata=(
                    {"sourceStorageBytes": source_storage_bytes}
                    if source_storage_bytes is not None
                    else {}
                ),
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

    @staticmethod
    async def _live_storage_bytes(db_connection: Any) -> Optional[int]:
        """Total relation size reported by ``analyze_storage`` (None if unsupported)."""
        try:
            analysis = await db_connection.analyze_storage()
            value = analysis.get("totalSize")
            return int(value) if value is not None else None
        except Exception:  # noqa: BLE001 - size context is optional
            rollback = getattr(
                getattr(db_connection, "connection", None), "rollback", None
            )
            if callable(rollback):
                try:
                    rollback()
                except Exception:  # noqa: BLE001
                    pass
            return None

    async def _materialize_payload(
        self,
        adapter: BackupAdapter,
        backup_info: BackupInfo,
        encryption_key: Optional[str],
    ) -> str:
        """Return a local, decrypted + decompressed dump path for ``backup_info``.

        Local returns an unpacked payload itself; remote adapters return the
        stored object, which is unpacked (and the download removed) here.
        """
        from .local import LocalBackupAdapter
        from .pipeline import unpack_payload

        stored = await adapter.restore_backup(
            backup_info, encryption_key=encryption_key
        )
        if isinstance(adapter, LocalBackupAdapter):
            return stored
        raw = Path(stored)
        try:
            passphrase = encryption_key or (backup_info.metadata or {}).get(
                "encryptionKey"
            )
            return str(unpack_payload(raw, backup_info.metadata or {}, passphrase))
        finally:
            raw.unlink(missing_ok=True)

    async def restore_backup(
        self,
        adapter: BackupAdapter,
        backup_info: BackupInfo,
        connection_config: ConnectionConfig,
        encryption_key: Optional[str] = None,
    ) -> None:
        """Low-level restore of ``backup_info`` into a database connection.

        This performs no safety checks; the GUI / API use :meth:`full_restore`,
        which adds the experimental gate, RBAC, confirmation and audit trail.
        """
        payload = await self._materialize_payload(
            adapter, backup_info, encryption_key
        )
        await self._apply_payload(payload, backup_info, connection_config)

    async def _apply_payload(
        self,
        payload: str,
        backup_info: BackupInfo,
        connection_config: ConnectionConfig,
    ) -> None:
        """Restore the unpacked ``payload`` into the target, then remove temp files."""
        try:
            effective = self._effective_connection_config(connection_config)
            db_connection = await DatabaseConnectionFactory.acquire(effective)
            try:
                await db_connection.restore_backup(payload)
            finally:
                await DatabaseConnectionFactory.release(db_connection)
        finally:
            # The materialized payload is always a private temp file, except
            # when a Local adapter hands back the stored (plain, uncompressed)
            # file itself.
            if payload != backup_info.path:
                Path(payload).unlink(missing_ok=True)

    @staticmethod
    def restore_confirmation_phrase(connection_config: ConnectionConfig) -> str:
        """Text the operator must type to authorise a restore into this target."""
        database = str(connection_config.database or "").strip()
        if "/" in database or "\\" in database:
            # File-based engines (SQLite): the file name, not a long absolute path.
            database = Path(database.replace("\\", "/")).name
        return database or str(connection_config.name)

    async def full_restore(
        self,
        adapter: BackupAdapter,
        backup_info: BackupInfo,
        connection_config: ConnectionConfig,
        *,
        confirmation: str,
        encryption_key: Optional[str] = None,
        safety_backup_dir: Optional[Path] = None,
        safety_passphrase: Optional[str] = None,
        on_stage: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Experimental, destructive restore into ``connection_config``.

        Order (nothing touches the target before step 5):

        1. experimental gate (``DSM_EXPERIMENTAL`` / Settings) and RBAC
           ``backups:restore``;
        2. typed confirmation must equal the target database name;
        3. engine of the backup must match the target engine;
        4. pre-flight: SHA-256, decrypt / decompress with the passphrase,
           SQLite integrity check (dry run) - fails here on a wrong passphrase;
        5. optional encrypted *safety backup* of the current target;
        6. restore through the engine driver.

        Every outcome is written to the audit log (no secrets).
        """
        from ..experimental import (
            ExperimentalDisabledError,
            require_restore_enabled,
        )
        from ..security.auth import PermissionDenied, get_auth_manager

        def stage(name: str) -> None:
            if on_stage:
                on_stage(name)

        audit_base = {
            "backupId": backup_info.id,
            "backupName": backup_info.name,
            "targetConnectionId": connection_config.id,
            "targetName": connection_config.name,
            "targetDatabase": connection_config.database,
            "adapter": type(adapter).__name__,
        }
        current_stage = "gate"
        remote_payload: Optional[str] = None
        try:
            stage("gate")
            require_restore_enabled()
            get_auth_manager().require("backups:restore")

            if (confirmation or "").strip() != self.restore_confirmation_phrase(
                connection_config
            ):
                raise RestoreRefused(
                    "Confirmation text does not match the target database name"
                )

            backup_family = _db_family(
                (backup_info.metadata or {}).get("databaseType")
            )
            if backup_family and backup_family != _db_family(
                connection_config.type
            ):
                raise RestoreRefused(
                    f"Backup was taken from a {backup_family} database; the "
                    f"target is {connection_config.type}"
                )

            current_stage = "preflight"
            stage("preflight")
            metadata = backup_info.metadata or {}
            passphrase = encryption_key or metadata.get("encryptionKey")
            if self.is_remote_backup(backup_info):
                verify = self.verify_backup(backup_info)
                if not verify.get("ok"):
                    raise RestoreRefused(
                        "Pre-flight checksum failed: "
                        f"{verify.get('error') or verify.get('status')}"
                    )
                # Download once and unpack now: a wrong passphrase or corrupt
                # archive must fail here, before a safety backup or any write.
                try:
                    remote_payload = await self._materialize_payload(
                        adapter, backup_info, passphrase
                    )
                except Exception as exc:  # noqa: BLE001
                    raise RestoreRefused(
                        f"Pre-flight could not unpack the backup: {exc}"
                    ) from exc
            else:
                dry = self.dry_run_restore(backup_info, encryption_key=passphrase)
                if not dry.get("ok"):
                    raise RestoreRefused(
                        f"Pre-flight dry run failed at {dry.get('stage')}: "
                        f"{dry.get('error')}"
                    )

            safety_name: Optional[str] = None
            if safety_backup_dir is not None:
                current_stage = "safety_backup"
                stage("safety_backup")
                if not safety_passphrase:
                    raise RestoreRefused(
                        "A safety backup needs its own encryption passphrase"
                    )
                from .local import LocalBackupAdapter

                safety = await self.create_backup(
                    LocalBackupAdapter(base_path=Path(safety_backup_dir)),
                    connection_config,
                    {
                        "compression": "zstd",
                        "encryption": True,
                        "encryptionKey": safety_passphrase,
                        "adapterType": "local",
                    },
                )
                safety_name = safety.name

            current_stage = "restore"
            stage("restore")
            if remote_payload is not None:
                payload_to_apply, remote_payload = remote_payload, None
                await self._apply_payload(
                    payload_to_apply, backup_info, connection_config
                )
            else:
                await self.restore_backup(
                    adapter, backup_info, connection_config, passphrase
                )
        except Exception as exc:
            if remote_payload is not None:
                Path(remote_payload).unlink(missing_ok=True)
            write_audit(
                "backup.restore",
                "refused"
                if isinstance(
                    exc,
                    (RestoreRefused, ExperimentalDisabledError, PermissionDenied),
                )
                else "failed",
                stage=current_stage,
                error=str(exc),
                **audit_base,
            )
            raise

        write_audit(
            "backup.restore",
            "completed",
            stage="restore",
            safetyBackup=safety_name,
            **audit_base,
        )
        stage("done")
        return {"ok": True, "safetyBackup": safety_name}

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

    @staticmethod
    def backup_destination(backup_info: BackupInfo) -> Optional[str]:
        """Canonical remote destination ("protondrive" / "s3" / ...) or None."""
        destination = str((backup_info.metadata or {}).get("destination") or "")
        return REMOTE_DESTINATIONS.get(destination.lower())

    @classmethod
    def is_remote_backup(cls, backup_info: BackupInfo) -> bool:
        """True when the listing came from a non-local destination."""
        return cls.backup_destination(backup_info) is not None

    def verify_backup(self, backup_info: BackupInfo) -> Dict[str, Any]:
        """Adapter-aware SHA-256 verification (local file or remote object).

        ``BackupInfo.path`` for remote rows is an rclone target or object key -
        never a local filesystem path - so it must not be checked with
        ``Path.exists``.
        """
        destination = self.backup_destination(backup_info)
        if destination is not None:
            adapter = self.get_adapter(destination)
            verify = getattr(adapter, "verify_remote_checksum", None)
            if verify is None:
                return {
                    "ok": False,
                    "status": "not_configured",
                    "id": backup_info.id,
                    "path": backup_info.path,
                    "expected": (backup_info.metadata or {}).get("sha256"),
                    "actual": None,
                    "error": f"{destination} adapter unavailable",
                }
            result = dict(verify(backup_info))
        else:
            result = self.verify_backup_checksum(backup_info)
        result.setdefault("id", backup_info.id)
        return result

    def verify_backups_parallel(
        self, backups: List[BackupInfo], *, remote_workers: int = 3
    ) -> List[Dict[str, Any]]:
        """Verify many backups: native parallel hashing for local files and
        adapter-aware checks (rclone download + SHA-256) for Proton Drive rows."""
        local = [b for b in backups if not self.is_remote_backup(b)]
        remote = [b for b in backups if self.is_remote_backup(b)]

        by_id: Dict[str, Dict[str, Any]] = {}
        for result in self._verify_local_parallel(local):
            by_id[str(result["id"])] = result

        if remote:
            workers = max(1, min(remote_workers, len(remote)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for backup, result in zip(remote, pool.map(self.verify_backup, remote)):
                    by_id[str(backup.id)] = result

        return [by_id[str(b.id)] for b in backups]

    def _verify_local_parallel(
        self, backups: List[BackupInfo]
    ) -> List[Dict[str, Any]]:
        if not backups:
            return []
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
