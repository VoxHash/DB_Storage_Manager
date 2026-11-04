"""S3-compatible backup adapter (AWS S3, MinIO, Cloudflare R2, Backblaze B2, ...).

Parity with the Local / Proton Drive adapters:

* compression (gzip / zstd) and DSMENC1 client-side encryption before upload
  (plaintext uploads are refused unless ``allowPlaintext`` is set explicitly);
* SHA-256 of the stored bytes kept as S3 user-metadata, re-checked by
  :meth:`S3BackupAdapter.verify_remote_checksum`;
* list / download / delete, plus ``dumpSize`` / ``sourceStorageBytes`` so the UI
  can explain why a backup is smaller than the live database.

Credentials never live in code: environment (``DSM_S3_*`` / ``AWS_*``), the
encrypted SecureStore ``s3_backup`` settings entry, or the default boto3
credential chain (profile / instance role) when no key pair is configured.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

from .base import BackupAdapter, BackupInfo, BackupOptions
from .pipeline import prepare_payload

DESTINATION = "s3"


class S3NotConfiguredError(RuntimeError):
    """Raised when no bucket / credentials are configured."""


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def resolve_s3_config(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge SecureStore ``s3_backup`` with environment overrides."""
    if settings is None:
        from ..security.store import SecureStore

        settings = SecureStore().get_settings()
    stored = dict(settings.get("s3_backup") or {})

    def pick(env_names, key, default=""):
        return _env_first(*env_names) or str(stored.get(key) or default)

    prefix = pick(("DSM_S3_PREFIX",), "prefix")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    config: Dict[str, Any] = {
        "bucket": pick(("DSM_S3_BUCKET",), "bucket"),
        "bucketPrefix": prefix,
        "endpoint": pick(("DSM_S3_ENDPOINT",), "endpoint") or None,
        "region": pick(
            ("DSM_S3_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"),
            "region",
            "us-east-1",
        ),
        "accessKeyId": pick(
            ("DSM_S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"), "accessKeyId"
        )
        or None,
        "secretAccessKey": pick(
            ("DSM_S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
            "secretAccessKey",
        )
        or None,
        "allowPlaintext": bool(stored.get("allowPlaintext", False)),
    }
    return config


def configuration_status(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Readiness summary for the UI (no network call)."""
    config = resolve_s3_config(settings)
    has_keys = bool(config["accessKeyId"] and config["secretAccessKey"])
    if not config["bucket"]:
        return {
            "configured": False,
            "bucket": "",
            "error": "No S3 bucket configured",
        }
    if bool(config["accessKeyId"]) != bool(config["secretAccessKey"]):
        return {
            "configured": False,
            "bucket": config["bucket"],
            "error": "Access key id and secret access key must be set together",
        }
    return {
        "configured": True,
        "bucket": config["bucket"],
        "prefix": config["bucketPrefix"],
        "endpoint": config["endpoint"],
        "region": config["region"],
        "credentials": "key pair" if has_keys else "default AWS credential chain",
    }


def save_s3_settings(
    *,
    bucket: str,
    prefix: str = "",
    region: str = "us-east-1",
    endpoint: str = "",
    access_key_id: Optional[str] = None,
    secret_access_key: Optional[str] = None,
    store: Any = None,
) -> Dict[str, Any]:
    """Persist S3 destination settings in the encrypted SecureStore file.

    Empty ``access_key_id`` / ``secret_access_key`` keep any stored value; pass
    ``""`` for both through :func:`clear_s3_credentials` to drop them.
    """
    if store is None:
        from ..security.store import SecureStore

        store = SecureStore()
    settings = store.get_settings()
    entry = dict(settings.get("s3_backup") or {})
    entry["bucket"] = bucket.strip()
    entry["prefix"] = prefix.strip()
    entry["region"] = region.strip() or "us-east-1"
    entry["endpoint"] = endpoint.strip()
    if access_key_id:
        entry["accessKeyId"] = access_key_id.strip()
    if secret_access_key:
        entry["secretAccessKey"] = secret_access_key
    settings["s3_backup"] = entry
    store.set_settings(settings)
    return entry


def clear_s3_credentials(store: Any = None) -> None:
    if store is None:
        from ..security.store import SecureStore

        store = SecureStore()
    settings = store.get_settings()
    entry = dict(settings.get("s3_backup") or {})
    entry.pop("accessKeyId", None)
    entry.pop("secretAccessKey", None)
    settings["s3_backup"] = entry
    store.set_settings(settings)


def _meta_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class S3BackupAdapter(BackupAdapter):
    """Store backups as objects in an S3-compatible bucket."""

    destination = DESTINATION

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config or {})
        self.bucket = str(self.config.get("bucket") or "")
        self.bucket_prefix = str(self.config.get("bucketPrefix") or "")
        self.allow_plaintext = bool(self.config.get("allowPlaintext", False))
        self._client = None

    @property
    def s3_client(self):
        if not self.bucket:
            raise S3NotConfiguredError("No S3 bucket configured")
        if self._client is None:
            import boto3

            kwargs: Dict[str, Any] = {
                "endpoint_url": self.config.get("endpoint") or None,
                "region_name": self.config.get("region") or "us-east-1",
            }
            key = self.config.get("accessKeyId")
            secret = self.config.get("secretAccessKey")
            if key and secret:
                kwargs["aws_access_key_id"] = key
                kwargs["aws_secret_access_key"] = secret
            elif key or secret:
                raise S3NotConfiguredError(
                    "Access key id and secret access key must be set together"
                )
            self._client = boto3.client("s3", **kwargs)
        return self._client

    # -- helpers -----------------------------------------------------------

    def _object_metadata(self, prepared, options: BackupOptions) -> Dict[str, str]:
        meta = {
            "backup-id": prepared.backup_id,
            "connection-id": str(options.connectionId),
            "connection-name": quote(str(options.connectionName), safe=""),
            "database-type": str(options.databaseType),
            "created-at": prepared.created_at.isoformat(),
            "compression": prepared.compression,
            "encryption": "true" if prepared.encrypted else "false",
            "sha256": prepared.sha256,
            "dump-size": str(prepared.dump_size),
        }
        live = prepared.metadata.get("sourceStorageBytes")
        if isinstance(live, int):
            meta["source-storage-bytes"] = str(live)
        return meta

    @staticmethod
    def _info_metadata(key: str, bucket: str, user_meta: Dict[str, str]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "key": key,
            "bucket": bucket,
            "destination": DESTINATION,
            "compression": user_meta.get("compression")
            or ("gzip" if ".gz" in key else "zstd" if ".zst" in key else "none"),
            "encryption": (user_meta.get("encryption") == "true")
            if "encryption" in user_meta
            else key.endswith(".enc"),
        }
        if user_meta.get("database-type"):
            meta["databaseType"] = user_meta["database-type"]
        if user_meta.get("connection-id"):
            meta["connectionId"] = user_meta["connection-id"]
        if user_meta.get("connection-name"):
            meta["connectionName"] = unquote(user_meta["connection-name"])
        if user_meta.get("sha256"):
            meta["sha256"] = user_meta["sha256"]
        for src, dest in (
            ("dump-size", "dumpSize"),
            ("source-storage-bytes", "sourceStorageBytes"),
        ):
            value = _meta_int(user_meta.get(src))
            if value is not None:
                meta[dest] = value
        if meta["encryption"]:
            from ..native import ENCRYPTION_SCHEME

            meta["encryptionScheme"] = ENCRYPTION_SCHEME
        return meta

    # -- BackupAdapter -------------------------------------------------------

    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        client = self.s3_client
        prepared = prepare_payload(
            options,
            require_encryption=not self.allow_plaintext,
            prefix="dsm-s3-",
        )
        try:
            key = f"{self.bucket_prefix}{prepared.filename}"
            user_meta = self._object_metadata(prepared, options)
            client.upload_file(
                str(prepared.path),
                self.bucket,
                key,
                ExtraArgs={"Metadata": user_meta},
            )
            return BackupInfo(
                id=prepared.backup_id,
                name=prepared.filename,
                path=key,
                size=prepared.size,
                createdAt=prepared.created_at,
                status="completed",
                metadata=self._info_metadata(key, self.bucket, user_meta),
            )
        finally:
            prepared.cleanup()

    def _download_to_temp(self, backup_info: BackupInfo) -> Path:
        key = (backup_info.metadata or {}).get("key") or backup_info.path
        fd, name = tempfile.mkstemp(suffix=".backup")
        os.close(fd)
        temp = Path(name)
        try:
            self.s3_client.download_file(self.bucket, str(key), str(temp))
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return temp

    async def restore_backup(
        self,
        backup_info: BackupInfo,
        encryption_key: Optional[str] = None,
    ) -> str:
        """Download the stored object (still encrypted / compressed).

        ``BackupManager`` decrypts and decompresses via ``unpack_payload``.
        """
        return str(self._download_to_temp(backup_info))

    async def list_backups(self) -> List[BackupInfo]:
        from botocore.exceptions import ClientError

        client = self.s3_client
        backups: List[BackupInfo] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=self.bucket_prefix
        ):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                name = Path(key).name
                if ".backup" not in name or name.endswith(".meta.json"):
                    continue
                try:
                    head = client.head_object(Bucket=self.bucket, Key=key)
                    user_meta = {
                        k.lower(): v for k, v in (head.get("Metadata") or {}).items()
                    }
                except ClientError:
                    user_meta = {}
                modified = obj.get("LastModified") or datetime.now(timezone.utc)
                backups.append(
                    BackupInfo(
                        id=user_meta.get("backup-id")
                        or str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL, f"s3://{self.bucket}/{key}"
                            )
                        ),
                        name=name,
                        path=key,
                        size=int(obj.get("Size") or 0),
                        createdAt=modified,
                        status="completed",
                        metadata=self._info_metadata(key, self.bucket, user_meta),
                    )
                )
        backups.sort(key=lambda b: b.createdAt, reverse=True)
        return backups

    async def delete_backup(self, backup_id: str) -> None:
        backups = await self.list_backups()
        backup = next((b for b in backups if b.id == backup_id), None)
        if backup is None:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        key = (backup.metadata or {}).get("key") or backup.path
        self.s3_client.delete_object(Bucket=self.bucket, Key=str(key))

    async def validate_options(self, options: BackupOptions) -> bool:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            return True
        except (ClientError, BotoCoreError, S3NotConfiguredError):
            return False

    def verify_remote_checksum(self, backup_info: BackupInfo) -> Dict[str, Any]:
        """Download the object and compare SHA-256 with the stored metadata."""
        from .pipeline import checksum_result

        local: Optional[Path] = None
        try:
            local = self._download_to_temp(backup_info)
            return checksum_result(backup_info, local)
        except S3NotConfiguredError as exc:
            return {
                "ok": False,
                "status": "not_configured",
                "path": backup_info.path,
                "expected": (backup_info.metadata or {}).get("sha256"),
                "actual": None,
                "error": str(exc),
            }
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
