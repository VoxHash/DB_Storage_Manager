"""Business logic for the REST companion (real SecureStore + BackupManager)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__
from ..backups.base import BackupInfo
from ..backups.local import LocalBackupAdapter
from ..backups.manager import BackupManager
from ..config import APP_NAME, APP_VERSION, BACKUP_DIR
from ..native import backend_info
from ..security.store import SecureStore
from .sanitize import sanitize_connections


def _run_async(coro):
    return asyncio.run(coro)


def health_payload() -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "healthy",
        "service": "db-storage-manager-api",
        "app": APP_NAME,
        "version": APP_VERSION,
        "package_version": __version__,
    }


def info_payload() -> Dict[str, Any]:
    native = backend_info()
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "package_version": __version__,
        "native": native,
        "backup_dir": str(BACKUP_DIR),
        "companion": "rest+web",
        "desktop_primary": True,
    }


def list_connections(store: Optional[SecureStore] = None) -> List[Dict[str, Any]]:
    store = store or SecureStore()
    return sanitize_connections(store.get_connections())


def list_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    adapter = LocalBackupAdapter(base_path=backup_dir or BACKUP_DIR)
    backups = _run_async(adapter.list_backups())
    return [_backup_to_dict(b) for b in backups]


def get_backup(
    backup_id: str, backup_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    for item in list_backups(backup_dir):
        if item.get("id") == backup_id:
            return item
    return None


def _backup_to_dict(info: BackupInfo) -> Dict[str, Any]:
    created = info.createdAt
    if isinstance(created, datetime):
        created_s = created.isoformat()
    else:
        created_s = str(created)
    return {
        "id": info.id,
        "name": info.name,
        "path": info.path,
        "size": info.size,
        "createdAt": created_s,
        "status": info.status,
        "metadata": dict(info.metadata or {}),
    }


def _info_from_dict(data: Dict[str, Any]) -> BackupInfo:
    created_raw = data.get("createdAt")
    if isinstance(created_raw, str):
        try:
            created = datetime.fromisoformat(created_raw)
        except ValueError:
            created = datetime.now()
    elif isinstance(created_raw, datetime):
        created = created_raw
    else:
        created = datetime.now()
    return BackupInfo(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or Path(str(data.get("path") or "")).name),
        path=str(data["path"]),
        size=int(data.get("size") or 0),
        createdAt=created,
        status=str(data.get("status") or "completed"),
        metadata=dict(data.get("metadata") or {}),
    )


def verify_backup(
    backup_id: Optional[str] = None,
    *,
    path: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    encryption_key: Optional[str] = None,
) -> Dict[str, Any]:
    info = _resolve_backup(backup_id=backup_id, path=path, backup_dir=backup_dir)
    if info is None:
        return {
            "ok": False,
            "status": "not_found",
            "error": "Backup not found",
        }
    manager = BackupManager()
    result = manager.verify_backup_checksum(info)
    result["id"] = info.id
    return result


def dry_run_backup(
    backup_id: Optional[str] = None,
    *,
    path: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    encryption_key: Optional[str] = None,
) -> Dict[str, Any]:
    info = _resolve_backup(backup_id=backup_id, path=path, backup_dir=backup_dir)
    if info is None:
        return {
            "ok": False,
            "status": "not_found",
            "stage": "lookup",
            "error": "Backup not found",
        }
    manager = BackupManager()
    result = manager.dry_run_restore(info, encryption_key=encryption_key)
    result["id"] = info.id
    return result


def _resolve_backup(
    backup_id: Optional[str],
    path: Optional[str],
    backup_dir: Optional[Path],
) -> Optional[BackupInfo]:
    if backup_id:
        data = get_backup(backup_id, backup_dir)
        if data is None:
            return None
        return _info_from_dict(data)
    if path:
        adapter = LocalBackupAdapter(base_path=backup_dir or BACKUP_DIR)
        backups = _run_async(adapter.list_backups())
        for item in backups:
            if item.path == path or Path(item.path).name == Path(path).name:
                return item
        # Ad-hoc path with sidecar metadata when listed under another dir
        p = Path(path)
        if not p.exists():
            return None
        stored = adapter._read_meta(p) or {}
        return BackupInfo(
            id=str(stored.get("id") or p.name),
            name=p.name,
            path=str(p),
            size=p.stat().st_size,
            createdAt=datetime.now(),
            status="completed",
            metadata={
                "compression": stored.get("compression") or "none",
                "encryption": bool(stored.get("encryption")),
                "databaseType": stored.get("databaseType"),
                "sha256": stored.get("sha256"),
            },
        )
    return None
