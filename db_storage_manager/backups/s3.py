"""
S3 backup adapter
"""

import json
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import uuid
import boto3
from botocore.exceptions import ClientError

from .base import BackupAdapter, BackupInfo, BackupOptions


class S3BackupAdapter(BackupAdapter):
    """S3 backup adapter"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=config.get("endpoint"),
            aws_access_key_id=config.get("accessKeyId"),
            aws_secret_access_key=config.get("secretAccessKey"),
            region_name=config.get("region", "us-east-1"),
        )
        self.bucket = config.get("bucket")
        self.bucket_prefix = config.get("bucketPrefix", "")

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Create an S3 backup"""
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{options.connectionName}_{timestamp}.backup"
        key = f"{self.bucket_prefix}{filename}" if self.bucket_prefix else filename

        source_path = Path(options.backupPath)
        if not source_path.exists():
            raise FileNotFoundError(f"Backup source file not found: {options.backupPath}")

        # Upload to S3
        metadata = {
            "backup-id": backup_id,
            "connection-id": options.connectionId,
            "database-type": options.databaseType,
            "created-at": datetime.now().isoformat(),
            "compression": options.compression or "none",
            "encryption": str(options.encryption or False),
        }

        self.s3_client.upload_file(
            str(source_path),
            self.bucket,
            key,
            ExtraArgs={"Metadata": metadata},
        )

        size = source_path.stat().st_size

        return BackupInfo(
            id=backup_id,
            name=filename,
            path=key,
            size=size,
            createdAt=datetime.now(),
            status="completed",
            metadata={
                "key": key,
                "bucket": self.bucket,
                "compression": options.compression or "none",
                "encryption": options.encryption or False,
                "databaseType": options.databaseType,
                "connectionId": options.connectionId,
            },
        )

    async def restore_backup(self, backup_info: BackupInfo) -> str:
        """Restore an S3 backup"""
        import tempfile

        key = backup_info.metadata.get("key") or backup_info.path
        temp_path = Path(tempfile.mktemp(suffix=".backup"))

        self.s3_client.download_file(self.bucket, key, str(temp_path))

        return str(temp_path)

    async def list_backups(self) -> list[BackupInfo]:
        """List all S3 backups"""
        backups = []

        prefix = self.bucket_prefix if self.bucket_prefix else ""
        paginator = self.s3_client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".backup"):
                    # Get metadata
                    try:
                        response = self.s3_client.head_object(
                            Bucket=self.bucket,
                            Key=obj["Key"],
                        )
                        metadata = response.get("Metadata", {})
                    except ClientError:
                        metadata = {}

                    backups.append(BackupInfo(
                        id=metadata.get("backup-id", str(uuid.uuid4())),
                        name=Path(obj["Key"]).name,
                        path=obj["Key"],
                        size=obj["Size"],
                        createdAt=obj["LastModified"],
                        status="completed",
                        metadata={
                            "key": obj["Key"],
                            "bucket": self.bucket,
                            **metadata,
                        },
                    ))

        return backups

    async def delete_backup(self, backup_id: str) -> None:
        """Delete an S3 backup"""
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)

        if backup:
            key = backup.metadata.get("key") or backup.path
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
        else:
            raise FileNotFoundError(f"Backup not found: {backup_id}")

    async def validate_options(self, options: BackupOptions) -> bool:
        """Validate backup options"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False

