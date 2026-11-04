"""Google Drive backup adapter (service account, adapter API only).

Status: **not exposed in the desktop UI**. A service account only sees files in
folders explicitly shared with it, uploads need resumable transfers and the
adapter cannot be exercised in CI without a live Google project, so it ships as
a library-level adapter until it is verified against a real account (see the
ROADMAP "backup adapter plugins" item). What it *does* guarantee is the same
safety contract as the supported adapters:

* gzip / zstd compression and DSMENC1 encryption go through the shared
  :mod:`pipeline` (plaintext uploads are refused unless ``allowPlaintext``);
* SHA-256 of the stored bytes is kept in Drive file ``properties``;
* uploads are resumable and downloads stream to disk (no whole-file ``BytesIO``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BackupAdapter, BackupInfo, BackupOptions
from .pipeline import checksum_result, prepare_payload

DESTINATION = "googledrive"
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveBackupAdapter(BackupAdapter):
    """Store backups in a Google Drive folder via a service account."""

    destination = DESTINATION

    def __init__(self, config: Dict[str, Any]):
        self.config = dict(config or {})
        self.folder_id = self.config.get("folderId")
        self.allow_plaintext = bool(self.config.get("allowPlaintext", False))
        credentials_info = self.config.get("serviceAccountCredentials")
        if not isinstance(credentials_info, dict):
            raise ValueError(
                "Google Drive adapter requires serviceAccountCredentials "
                "(service account JSON as a dict)"
            )
        # Imported here so a missing / broken Google stack never breaks
        # ``import db_storage_manager.backups``.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=_SCOPES
        )
        self.drive_service = build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )

    @staticmethod
    def _parse_time(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now()
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _info_metadata(file_id: str, folder: Optional[str], props: Dict[str, str]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "fileId": file_id,
            "folderId": folder,
            "destination": DESTINATION,
            "compression": props.get("compression", "none"),
            "encryption": props.get("encryption") == "true",
        }
        if props.get("database-type"):
            meta["databaseType"] = props["database-type"]
        if props.get("connection-id"):
            meta["connectionId"] = props["connection-id"]
        if props.get("sha256"):
            meta["sha256"] = props["sha256"]
        for src, dest in (
            ("dump-size", "dumpSize"),
            ("source-storage-bytes", "sourceStorageBytes"),
        ):
            try:
                meta[dest] = int(props[src])
            except (KeyError, ValueError):
                pass
        if meta["encryption"]:
            from ..native import ENCRYPTION_SCHEME

            meta["encryptionScheme"] = ENCRYPTION_SCHEME
        return meta

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        prepared = prepare_payload(
            options,
            require_encryption=not self.allow_plaintext,
            prefix="dsm-gdrive-",
        )
        try:
            props = {
                "backup-id": prepared.backup_id,
                "connection-id": str(options.connectionId),
                "database-type": str(options.databaseType),
                "created-at": prepared.created_at.isoformat(),
                "compression": prepared.compression,
                "encryption": "true" if prepared.encrypted else "false",
                "sha256": prepared.sha256,
                "dump-size": str(prepared.dump_size),
            }
            live = prepared.metadata.get("sourceStorageBytes")
            if isinstance(live, int):
                props["source-storage-bytes"] = str(live)
            body: Dict[str, Any] = {
                "name": prepared.filename,
                "properties": props,
            }
            if self.folder_id:
                body["parents"] = [self.folder_id]
            media = MediaFileUpload(
                str(prepared.path),
                mimetype="application/octet-stream",
                resumable=True,
            )
            try:
                file = (
                    self.drive_service.files()
                    .create(
                        body=body,
                        media_body=media,
                        fields="id, name, size, createdTime, parents, properties",
                    )
                    .execute()
                )
            except HttpError as error:
                raise RuntimeError(f"Google Drive upload failed: {error}") from error
            return BackupInfo(
                id=prepared.backup_id,
                name=file.get("name"),
                path=file.get("id"),
                size=int(file.get("size") or prepared.size),
                createdAt=self._parse_time(file.get("createdTime")),
                status="completed",
                metadata=self._info_metadata(
                    file.get("id"), self.folder_id, props
                ),
            )
        finally:
            prepared.cleanup()

    def _download_to_temp(self, backup_info: BackupInfo) -> Path:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaIoBaseDownload

        file_id = (backup_info.metadata or {}).get("fileId") or backup_info.path
        request = self.drive_service.files().get_media(fileId=file_id)
        fd, name = tempfile.mkstemp(suffix=".backup")
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                downloader = MediaIoBaseDownload(
                    handle, request, chunksize=8 * 1024 * 1024
                )
                done = False
                while not done:
                    _status, done = downloader.next_chunk()
        except HttpError as error:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"Google Drive download failed: {error}") from error
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return temp

    async def restore_backup(
        self,
        backup_info: BackupInfo,
        encryption_key: Optional[str] = None,
    ) -> str:
        """Download the stored file (still encrypted / compressed)."""
        return str(self._download_to_temp(backup_info))

    async def list_backups(self) -> List[BackupInfo]:
        from googleapiclient.errors import HttpError

        clauses = ["trashed = false", "name contains '.backup'"]
        if self.folder_id:
            clauses.insert(0, f"'{_escape_query(str(self.folder_id))}' in parents")
        query = " and ".join(clauses)
        backups: List[BackupInfo] = []
        page_token = None
        try:
            while True:
                result = (
                    self.drive_service.files()
                    .list(
                        q=query,
                        fields=(
                            "nextPageToken, files(id, name, size, createdTime, "
                            "parents, properties)"
                        ),
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
                for file in result.get("files", []):
                    props = file.get("properties") or {}
                    parents = file.get("parents") or [None]
                    backups.append(
                        BackupInfo(
                            id=props.get("backup-id")
                            or str(uuid.uuid5(uuid.NAMESPACE_URL, file["id"])),
                            name=file.get("name"),
                            path=file.get("id"),
                            size=int(file.get("size") or 0),
                            createdAt=self._parse_time(file.get("createdTime")),
                            status="completed",
                            metadata=self._info_metadata(
                                file["id"], parents[0], props
                            ),
                        )
                    )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as error:
            raise RuntimeError(f"Google Drive list failed: {error}") from error
        return backups

    async def delete_backup(self, backup_id: str) -> None:
        from googleapiclient.errors import HttpError

        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)
        if backup is None:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        file_id = (backup.metadata or {}).get("fileId") or backup.path
        try:
            self.drive_service.files().delete(fileId=file_id).execute()
        except HttpError as error:
            raise RuntimeError(f"Google Drive delete failed: {error}") from error

    async def validate_options(self, options: BackupOptions) -> bool:
        from googleapiclient.errors import HttpError

        try:
            self.drive_service.files().list(pageSize=1).execute()
            return True
        except HttpError:
            return False

    def verify_remote_checksum(self, backup_info: BackupInfo) -> Dict[str, Any]:
        local: Optional[Path] = None
        try:
            local = self._download_to_temp(backup_info)
            return checksum_result(backup_info, local)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "status": "fail",
                "path": backup_info.path,
                "expected": (backup_info.metadata or {}).get("sha256"),
                "actual": None,
                "error": str(exc),
            }
        finally:
            if local is not None:
                local.unlink(missing_ok=True)
