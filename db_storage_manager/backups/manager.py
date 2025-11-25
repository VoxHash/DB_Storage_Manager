"""
Backup manager for coordinating backup operations
"""

from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
import tempfile

from .base import BackupAdapter, BackupInfo, BackupOptions
from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig


class BackupManager:
    """Manages backup operations across different adapters"""

    def __init__(self):
        self.adapters: Dict[str, BackupAdapter] = {}

    def register_adapter(self, adapter_type: str, adapter: BackupAdapter) -> None:
        """Register a backup adapter"""
        self.adapters[adapter_type] = adapter

    def get_adapter(self, adapter_type: str, config: Optional[Dict[str, Any]] = None) -> Optional[BackupAdapter]:
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
        # Create database connection
        db_connection = DatabaseConnectionFactory.create_connection(connection_config)
        await db_connection.connect()

        try:
            # Create temporary backup file
            temp_dir = Path(tempfile.gettempdir())
            temp_backup = temp_dir / f"{connection_config.name}_{__import__('time').time()}.tmpbackup"

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
            await db_connection.disconnect()

    async def restore_backup(
        self,
        adapter: BackupAdapter,
        backup_info: BackupInfo,
        connection_config: ConnectionConfig,
    ) -> None:
        """Restore a backup to a database connection"""
        # Download backup from adapter if needed
        local_backup_path = await adapter.restore_backup(backup_info)

        try:
            # Create database connection
            db_connection = DatabaseConnectionFactory.create_connection(connection_config)
            await db_connection.connect()

            try:
                # Restore backup
                await db_connection.restore_backup(local_backup_path)
            finally:
                await db_connection.disconnect()
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
                    on_progress({"connectionId": connection.id, "status": "in_progress"})

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
                    on_progress({"connectionId": connection.id, "status": "failed", "error": str(e)})

        return results

