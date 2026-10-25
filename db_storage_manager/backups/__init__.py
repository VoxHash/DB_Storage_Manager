"""
Backup system modules
"""

from .base import BackupAdapter, BackupInfo, BackupOptions
from .manager import BackupManager
from .local import LocalBackupAdapter
from .s3 import S3BackupAdapter
from .googledrive import GoogleDriveBackupAdapter
from .protondrive import (
    ProtonDriveBackupAdapter,
    ProtonDriveNotConfiguredError,
    configuration_status as proton_drive_configuration_status,
    resolve_proton_drive_config,
)

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
