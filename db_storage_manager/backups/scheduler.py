"""
Scheduled backup manager
"""

import json
import schedule
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid

from .manager import BackupManager
from .base import BackupAdapter
from ..db.base import ConnectionConfig
from ..config import SCHEDULED_BACKUPS_FILE, USER_DATA_DIR
from ..security.store import SecureStore


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
    """Manages scheduled backups"""

    def __init__(self):
        self.backup_manager = BackupManager()
        self.secure_store = SecureStore()
        self.schedules: List[ScheduledBackup] = []
        self.scheduler_thread: Optional[threading.Thread] = None
        self.running = False
        self.load_schedules()

    def load_schedules(self) -> None:
        """Load scheduled backups from file"""
        if SCHEDULED_BACKUPS_FILE.exists():
            try:
                data = json.loads(SCHEDULED_BACKUPS_FILE.read_text())
                self.schedules = [ScheduledBackup.from_dict(s) for s in data]
            except Exception:
                self.schedules = []
        else:
            self.schedules = []

    def save_schedules(self) -> None:
        """Save scheduled backups to file"""
        data = [s.to_dict() for s in self.schedules]
        SCHEDULED_BACKUPS_FILE.write_text(json.dumps(data, indent=2))

    def get_schedules(self) -> List[ScheduledBackup]:
        """Get all scheduled backups"""
        return self.schedules.copy()

    def get_schedule(self, schedule_id: str) -> Optional[ScheduledBackup]:
        """Get a scheduled backup by ID"""
        return next((s for s in self.schedules if s.id == schedule_id), None)

    def create_schedule(self, schedule_data: Dict[str, Any]) -> ScheduledBackup:
        """Create a new scheduled backup"""
        schedule = ScheduledBackup(
            id=str(uuid.uuid4()),
            name=schedule_data["name"],
            interval_minutes=schedule_data["intervalMinutes"],
            enabled=schedule_data.get("enabled", True),
            adapter_type=schedule_data["adapterType"],
            adapter_config=schedule_data.get("adapterConfig"),
            connections=schedule_data["connections"],
        )
        self.schedules.append(schedule)
        self.save_schedules()

        if schedule.enabled:
            self._start_schedule(schedule)

        return schedule

    def update_schedule(self, schedule_data: Dict[str, Any]) -> ScheduledBackup:
        """Update a scheduled backup"""
        schedule_id = schedule_data["id"]
        schedule = self.get_schedule(schedule_id)

        if not schedule:
            raise ValueError(f"Scheduled backup not found: {schedule_id}")

        # Stop existing schedule
        self._stop_schedule(schedule)

        # Update schedule
        schedule.name = schedule_data["name"]
        schedule.interval_minutes = schedule_data["intervalMinutes"]
        schedule.enabled = schedule_data.get("enabled", True)
        schedule.adapter_type = schedule_data["adapterType"]
        schedule.adapter_config = schedule_data.get("adapterConfig")
        schedule.connections = schedule_data["connections"]

        self.save_schedules()

        if schedule.enabled:
            self._start_schedule(schedule)

        return schedule

    def delete_schedule(self, schedule_id: str) -> None:
        """Delete a scheduled backup"""
        schedule = self.get_schedule(schedule_id)

        if schedule:
            self._stop_schedule(schedule)
            self.schedules.remove(schedule)
            self.save_schedules()

    def _start_schedule(self, schedule: ScheduledBackup) -> None:
        """Start a scheduled backup"""

        def job():
            self._execute_backup(schedule)

        # Schedule the job using the schedule module
        schedule_module = __import__("schedule")
        schedule_module.every(schedule.interval_minutes).minutes.do(job)

    def _stop_schedule(self, schedule: ScheduledBackup) -> None:
        """Stop a scheduled backup"""
        # Clear all jobs - this is a limitation of the schedule module
        # In a production system, you'd want to track jobs individually
        schedule_module = __import__("schedule")
        schedule_module.clear()

    def _execute_backup(self, schedule: ScheduledBackup) -> None:
        """Execute a scheduled backup"""
        try:
            # Get connections
            connections = self.secure_store.get_connections()
            if schedule.connections == "all":
                target_connections = [ConnectionConfig(**conn) for conn in connections]
            else:
                target_connections = [
                    ConnectionConfig(**conn)
                    for conn in connections
                    if conn["id"] in schedule.connections
                ]

            if not target_connections:
                return

            # Get adapter
            adapter = self.backup_manager.get_adapter(
                schedule.adapter_type,
                schedule.adapter_config,
            )

            if not adapter:
                return

            # Execute batch backup
            import asyncio

            asyncio.run(
                self.backup_manager.create_batch_backups(
                    target_connections,
                    adapter,
                    {
                        "adapterType": schedule.adapter_type,
                        "adapterConfig": schedule.adapter_config,
                    },
                )
            )

            schedule.last_run = datetime.now()
            self.save_schedules()
        except Exception as e:
            print(f"Error executing scheduled backup {schedule.name}: {e}")

    def start(self) -> None:
        """Start the scheduler thread"""
        if self.running:
            return

        self.running = True

        def run_scheduler():
            schedule_module = __import__("schedule")
            while self.running:
                schedule_module.run_pending()
                import time

                time.sleep(1)

        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()

        # Start all enabled schedules
        for schedule in self.schedules:
            if schedule.enabled:
                self._start_schedule(schedule)

    def stop(self) -> None:
        """Stop the scheduler thread"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
