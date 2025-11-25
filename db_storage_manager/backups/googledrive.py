"""
Google Drive backup adapter
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import uuid
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

from .base import BackupAdapter, BackupInfo, BackupOptions


class GoogleDriveBackupAdapter(BackupAdapter):
    """Google Drive backup adapter"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.folder_id = config.get("folderId")

        # Initialize Google Drive API
        credentials = service_account.Credentials.from_service_account_info(
            config.get("serviceAccountCredentials"),
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        self.drive_service = build("drive", "v3", credentials=credentials)

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Create a Google Drive backup"""
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{options.connectionName}_{timestamp}.backup"

        source_path = Path(options.backupPath)
        if not source_path.exists():
            raise FileNotFoundError(f"Backup source file not found: {options.backupPath}")

        # Prepare file metadata
        file_metadata = {
            "name": filename,
            "properties": {
                "backup-id": backup_id,
                "connection-id": options.connectionId,
                "database-type": options.databaseType,
                "created-at": datetime.now().isoformat(),
                "compression": options.compression or "none",
                "encryption": str(options.encryption or False),
            },
        }

        if self.folder_id:
            file_metadata["parents"] = [self.folder_id]

        # Upload file
        media = MediaFileUpload(str(source_path), mimetype="application/octet-stream")

        try:
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, size, createdTime, parents, properties",
            ).execute()

            size = int(file.get("size", 0))

            return BackupInfo(
                id=backup_id,
                name=file.get("name"),
                path=file.get("id"),
                size=size,
                createdAt=datetime.fromisoformat(file.get("createdTime").replace("Z", "+00:00")),
                status="completed",
                metadata={
                    "fileId": file.get("id"),
                    "folderId": self.folder_id,
                    "compression": options.compression or "none",
                    "encryption": options.encryption or False,
                    "databaseType": options.databaseType,
                    "connectionId": options.connectionId,
                },
            )
        except HttpError as error:
            raise RuntimeError(f"Google Drive upload failed: {error}")

    async def restore_backup(self, backup_info: BackupInfo) -> str:
        """Restore a Google Drive backup"""
        import tempfile
        import io

        file_id = backup_info.metadata.get("fileId") or backup_info.path
        temp_path = Path(tempfile.mktemp(suffix=".backup"))

        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            file_data = io.BytesIO()
            downloader = MediaIoBaseDownload(file_data, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            file_data.seek(0)
            temp_path.write_bytes(file_data.read())

            return str(temp_path)
        except HttpError as error:
            raise RuntimeError(f"Google Drive download failed: {error}")

    async def list_backups(self) -> list[BackupInfo]:
        """List all Google Drive backups"""
        backups = []

        query = f"'{self.folder_id}' in parents and trashed = false" if self.folder_id else "trashed = false"
        query += " and name contains '.backup'"

        try:
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, size, createdTime, parents, properties)",
                pageSize=1000,
            ).execute()

            files = results.get("files", [])

            for file in files:
                properties = file.get("properties", {})
                backups.append(BackupInfo(
                    id=properties.get("backup-id", str(uuid.uuid4())),
                    name=file.get("name"),
                    path=file.get("id"),
                    size=int(file.get("size", 0)),
                    createdAt=datetime.fromisoformat(file.get("createdTime").replace("Z", "+00:00")),
                    status="completed",
                    metadata={
                        "fileId": file.get("id"),
                        "folderId": file.get("parents", [None])[0] if file.get("parents") else None,
                        "compression": properties.get("compression", "none"),
                        "encryption": properties.get("encryption") == "True",
                        "databaseType": properties.get("database-type"),
                        "connectionId": properties.get("connection-id"),
                    },
                ))
        except HttpError as error:
            raise RuntimeError(f"Google Drive list failed: {error}")

        return backups

    async def delete_backup(self, backup_id: str) -> None:
        """Delete a Google Drive backup"""
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)

        if backup:
            file_id = backup.metadata.get("fileId") or backup.path
            try:
                self.drive_service.files().delete(fileId=file_id).execute()
            except HttpError as error:
                raise RuntimeError(f"Google Drive delete failed: {error}")
        else:
            raise FileNotFoundError(f"Backup not found: {backup_id}")

    async def validate_options(self, options: BackupOptions) -> bool:
        """Validate backup options"""
        try:
            self.drive_service.files().list(pageSize=1).execute()
            return True
        except HttpError:
            return False

