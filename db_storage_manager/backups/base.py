"""
Base backup adapter interface
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BackupInfo:
    """Backup information"""

    id: str
    name: str
    path: str
    size: int
    createdAt: datetime
    status: str
    metadata: Dict[str, Any]


@dataclass
class BackupOptions:
    """Backup options"""

    connectionId: str
    connectionName: str
    databaseType: str
    backupPath: str
    compression: Optional[str] = None  # none, gzip, zstd
    encryption: bool = False
    encryptionKey: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    adapterType: Optional[str] = None  # local, s3, googledrive
    adapterConfig: Optional[Dict[str, Any]] = None


class BackupAdapter(ABC):
    """Base class for backup adapters"""

    @abstractmethod
    async def create_backup(self, options: BackupOptions) -> BackupInfo:
        """Create a backup"""
        pass

    @abstractmethod
    async def restore_backup(self, backup_info: BackupInfo) -> str:
        """Restore a backup and return local file path"""
        pass

    @abstractmethod
    async def list_backups(self) -> list[BackupInfo]:
        """List all backups"""
        pass

    @abstractmethod
    async def delete_backup(self, backup_id: str) -> None:
        """Delete a backup"""
        pass

    @abstractmethod
    async def validate_options(self, options: BackupOptions) -> bool:
        """Validate backup options"""
        pass
