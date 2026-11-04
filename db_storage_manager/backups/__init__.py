"""
Backup system modules

Adapter classes that pull in optional / heavy SDKs (boto3, Google API client)
are resolved lazily so ``import db_storage_manager.backups`` never fails when
one of those stacks is missing or broken.
"""

from .base import BackupAdapter, BackupInfo, BackupOptions
from .manager import BackupManager
from .local import LocalBackupAdapter
from .protondrive import (
    ProtonDriveBackupAdapter,
    ProtonDriveNotConfiguredError,
    configuration_status as proton_drive_configuration_status,
    resolve_proton_drive_config,
)

_LAZY = {
    "S3BackupAdapter": (".s3", "S3BackupAdapter"),
    "GoogleDriveBackupAdapter": (".googledrive", "GoogleDriveBackupAdapter"),
}


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(target[0], __name__), target[1])


__all__ = [
    "BackupAdapter",
    "BackupInfo",
    "BackupOptions",
    "BackupManager",
    "LocalBackupAdapter",
    "S3BackupAdapter",
    "GoogleDriveBackupAdapter",
    "ProtonDriveBackupAdapter",
    "ProtonDriveNotConfiguredError",
    "proton_drive_configuration_status",
    "resolve_proton_drive_config",
]
