"""
Scheduled backup manager
"""

import json
import logging
import os
import schedule
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid

from .manager import ENCRYPTED_ADAPTERS, BackupManager
from .base import BackupAdapter
from ..db.base import ConnectionConfig
from ..config import SCHEDULED_BACKUPS_FILE, USER_DATA_DIR
from ..security.store import SecureStore

logger = logging.getLogger(__name__)

# Max scheduled dumps running at once (each runs in its own worker thread).
MAX_CONCURRENT_SCHEDULED_RUNS = 2


class ScheduledBackup:
    """Scheduled backup configuration"""

    def __init__(
        self,
        id: str,
        name: str,
        interval_minutes: int,
        enabled: bool,
        adapter_type: str,
        adapter_config: Optional[Dict[str, Any]],
        connections: List[str],  # List of connection IDs or "all"
    ):
        self.id = id
        self.name = name
        self.interval_minutes = interval_minutes
        self.enabled = enabled
        self.adapter_type = adapter_type
        self.adapter_config = adapter_config
        self.connections = connections
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "intervalMinutes": self.interval_minutes,
            "enabled": self.enabled,
            "adapterType": self.adapter_type,
            "adapterConfig": self.adapter_config,
            "connections": self.connections,
            "lastRun": self.last_run.isoformat() if self.last_run else None,
            "nextRun": self.next_run.isoformat() if self.next_run else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledBackup":
        """Create from dictionary"""
        instance = cls(
            id=data["id"],
            name=data["name"],
            interval_minutes=data["intervalMinutes"],
            enabled=data["enabled"],
            adapter_type=data["adapterType"],
            adapter_config=data.get("adapterConfig"),
            connections=data["connections"],
        )
        if data.get("lastRun"):
            instance.last_run = datetime.fromisoformat(data["lastRun"])
        if data.get("nextRun"):
            instance.next_run = datetime.fromisoformat(data["nextRun"])
        return instance


class ScheduledBackupManager:
    """Manages scheduled backups.

    Uses a private ``schedule.Scheduler`` (not the process-global one) guarded
    by a lock, so GUI add/toggle/remove calls cannot race the scheduler thread.
    Each due job runs in its own worker thread; a schedule that is still running
    is skipped instead of piling up, and at most
    ``MAX_CONCURRENT_SCHEDULED_RUNS`` dumps execute at the same time.
    """

    def __init__(self):
        self.backup_manager = BackupManager()
        self.secure_store = SecureStore()
        self.schedules: List[ScheduledBackup] = []
        self.scheduler_thread: Optional[threading.Thread] = None
        self.running = False
        self._scheduler = schedule.Scheduler()
        self._lock = threading.RLock()
        self._run_locks: Dict[str, threading.Lock] = {}
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_SCHEDULED_RUNS)
        self.load_schedules()

    # -- persistence ---------------------------------------------------

    def load_schedules(self) -> None:
        """Load scheduled backups from file (migrating legacy plaintext keys)."""
        with self._lock:
            if SCHEDULED_BACKUPS_FILE.exists():
                try:
                    data = json.loads(SCHEDULED_BACKUPS_FILE.read_text())
                    self.schedules = [ScheduledBackup.from_dict(s) for s in data]
                except Exception:
                    self.schedules = []
            else:
                self.schedules = []
            self._migrate_plaintext_secrets()

    def _migrate_plaintext_secrets(self) -> None:
        """Move any ``encryptionKey`` found in the JSON into the encrypted store."""
        migrated = False
        for item in self.schedules:
            cfg = item.adapter_config
            if isinstance(cfg, dict) and cfg.get("encryptionKey"):
                self._store_secret(item.id, str(cfg["encryptionKey"]))
                item.adapter_config = {
                    k: v for k, v in cfg.items() if k != "encryptionKey"
                }
                migrated = True
        if migrated:
            self.save_schedules()

    def save_schedules(self) -> None:
        """Save scheduled backups to file (atomic, mode 600, no secrets)."""
        with self._lock:
            data = [s.to_dict() for s in self.schedules]
            tmp = SCHEDULED_BACKUPS_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2))
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            tmp.replace(SCHEDULED_BACKUPS_FILE)

    # -- passphrase vault ----------------------------------------------

    def _store_secret(self, schedule_id: str, passphrase: str) -> None:
        secrets = self.secure_store.get_scheduled_backup_secrets()
        secrets[schedule_id] = passphrase
        self.secure_store.save_scheduled_backup_secrets(secrets)

    def _load_secret(self, schedule_id: str) -> Optional[str]:
        return self.secure_store.get_scheduled_backup_secrets().get(schedule_id)

    def _drop_secret(self, schedule_id: str) -> None:
        secrets = self.secure_store.get_scheduled_backup_secrets()
        if schedule_id in secrets:
            del secrets[schedule_id]
            self.secure_store.save_scheduled_backup_secrets(secrets)

    def has_encryption_key(self, schedule_id: str) -> bool:
        return bool(self._load_secret(schedule_id))

    def _split_adapter_config(
        self, schedule_id: str, adapter_config: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Persist any passphrase in the encrypted vault; return the public config."""
        if adapter_config is None:
            return None
        cfg = dict(adapter_config)
        key = cfg.pop("encryptionKey", None)
        if key:
            self._store_secret(schedule_id, str(key))
        return cfg

    # -- CRUD ----------------------------------------------------------

    def get_schedules(self) -> List[ScheduledBackup]:
        """Get all scheduled backups"""
        with self._lock:
            return self.schedules.copy()

    def get_schedule(self, schedule_id: str) -> Optional[ScheduledBackup]:
        """Get a scheduled backup by ID"""
        with self._lock:
            return next((s for s in self.schedules if s.id == schedule_id), None)

    def create_schedule(self, schedule_data: Dict[str, Any]) -> ScheduledBackup:
        """Create a new scheduled backup"""
        schedule_id = str(uuid.uuid4())
        with self._lock:
            item = ScheduledBackup(
                id=schedule_id,
                name=schedule_data["name"],
                interval_minutes=schedule_data["intervalMinutes"],
                enabled=schedule_data.get("enabled", True),
                adapter_type=schedule_data["adapterType"],
                adapter_config=self._split_adapter_config(
                    schedule_id, schedule_data.get("adapterConfig")
                ),
                connections=schedule_data["connections"],
            )
            self.schedules.append(item)
            self.save_schedules()

            if item.enabled:
                self._start_schedule(item)

            return item

    def update_schedule(self, schedule_data: Dict[str, Any]) -> ScheduledBackup:
        """Update a scheduled backup (a stored passphrase is kept unless replaced)."""
        schedule_id = schedule_data["id"]
        with self._lock:
            item = self.get_schedule(schedule_id)

            if not item:
                raise ValueError(f"Scheduled backup not found: {schedule_id}")

            self._stop_schedule(item)

            item.name = schedule_data["name"]
            item.interval_minutes = schedule_data["intervalMinutes"]
            item.enabled = schedule_data.get("enabled", True)
            item.adapter_type = schedule_data["adapterType"]
            item.adapter_config = self._split_adapter_config(
                schedule_id, schedule_data.get("adapterConfig")
            )
            item.connections = schedule_data["connections"]

            self.save_schedules()

            if item.enabled:
                self._start_schedule(item)

            return item

    def delete_schedule(self, schedule_id: str) -> None:
        """Delete a scheduled backup (and its stored passphrase)."""
        with self._lock:
            item = self.get_schedule(schedule_id)

            if item:
                self._stop_schedule(item)
                self.schedules.remove(item)
                self._run_locks.pop(schedule_id, None)
                self._drop_secret(schedule_id)
                self.save_schedules()

    # -- scheduling ----------------------------------------------------

    def _start_schedule(self, item: ScheduledBackup) -> None:
        """Register one tagged job (other schedules are untouched)."""

        def job():
            self._dispatch(item)

        with self._lock:
            self._scheduler.clear(item.id)
            (
                self._scheduler.every(item.interval_minutes)
                .minutes.do(job)
                .tag(item.id)
            )
            jobs = self._scheduler.get_jobs(item.id)
            item.next_run = jobs[0].next_run if jobs else None

    def _stop_schedule(self, item: ScheduledBackup) -> None:
        """Stop one scheduled backup without clearing unrelated jobs."""
        with self._lock:
            self._scheduler.clear(item.id)
            item.next_run = None

    def is_scheduled(self, schedule_id: str) -> bool:
        with self._lock:
            return bool(self._scheduler.get_jobs(schedule_id))

    def _dispatch(self, item: ScheduledBackup) -> bool:
        """Run ``item`` in a worker thread unless it is already running."""
        with self._lock:
            run_lock = self._run_locks.setdefault(item.id, threading.Lock())
        if not run_lock.acquire(blocking=False):
            logger.warning(
                "Scheduled backup %s is still running; skipping this tick", item.name
            )
            return False

        def _run() -> None:
            try:
                with self._slots:
                    self._execute_backup(item)
            finally:
                run_lock.release()

        threading.Thread(
            target=_run, name=f"dsm-schedule-{item.id[:8]}", daemon=True
        ).start()
        return True

    def run_now(self, schedule_id: str) -> bool:
        """Trigger one schedule immediately (worker thread). False if unknown/busy."""
        item = self.get_schedule(schedule_id)
        if item is None:
            return False
        return self._dispatch(item)

    def _execute_backup(self, item: ScheduledBackup) -> None:
        """Execute a scheduled backup"""
        try:
            connections = self.secure_store.get_connections()
            if item.connections == "all":
                target_connections = [ConnectionConfig(**conn) for conn in connections]
            else:
                target_connections = [
                    ConnectionConfig(**conn)
                    for conn in connections
                    if conn["id"] in item.connections
                ]

            if not target_connections:
                return

            cfg = dict(item.adapter_config or {})
            passphrase = cfg.get("encryptionKey") or self._load_secret(item.id)

            adapter = self.backup_manager.get_adapter(item.adapter_type, cfg)

            if not adapter:
                return

            import asyncio

            options = {
                "adapterType": item.adapter_type,
                "adapterConfig": cfg,
                "compression": cfg.get("compression") or "none",
                "encryption": bool(
                    cfg.get("encryption", item.adapter_type in ENCRYPTED_ADAPTERS)
                ),
                "encryptionKey": passphrase,
            }
            # Opsec: off-machine destinations always encrypt before upload.
            if item.adapter_type in ENCRYPTED_ADAPTERS:
                options["encryption"] = True
            if options["encryption"] and not passphrase:
                logger.error(
                    "Scheduled backup %s requires an encryption passphrase "
                    "(adapter=%s); skipping run.",
                    item.name,
                    item.adapter_type,
                )
                return

            results = asyncio.run(
                self.backup_manager.create_batch_backups(
                    target_connections,
                    adapter,
                    options,
                )
            )
            try:
                from .retention import prune_scheduled

                asyncio.run(
                    prune_scheduled(
                        adapter, item.adapter_type, results, self.secure_store
                    )
                )
            except Exception:
                logger.exception(
                    "Retention prune failed after scheduled backup %s", item.name
                )

            item.last_run = datetime.now()
            self.save_schedules()
        except Exception as e:
            logger.exception("Error executing scheduled backup %s: %s", item.name, e)

    def start(self) -> None:
        """Start the scheduler thread"""
        with self._lock:
            if self.running:
                return
            self.running = True

        def run_scheduler():
            while self.running:
                with self._lock:
                    self._scheduler.run_pending()
                time.sleep(1)

        self.scheduler_thread = threading.Thread(
            target=run_scheduler, name="dsm-scheduler", daemon=True
        )
        self.scheduler_thread.start()

        with self._lock:
            for item in self.schedules:
                if item.enabled:
                    self._start_schedule(item)

    def stop(self) -> None:
        """Stop the scheduler thread"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
