"""Retention keeps the newest copy per day and per month. Off deletes nothing."""

from __future__ import annotations

from datetime import datetime, timezone

import asyncio

from db_storage_manager.backups.base import BackupInfo
from db_storage_manager.backups.retention import plan_prune, policy_for, prune_connection


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=timezone.utc)


def _info(ident: str, when: datetime, connection: str = "c1") -> BackupInfo:
    return BackupInfo(
        id=ident,
        name=ident,
        path=f"/tmp/{ident}",
        size=1,
        createdAt=when,
        status="completed",
        metadata={"connectionId": connection},
    )


def test_daily_and_monthly_keep_newest_of_each_bucket():
    backups = [
        {"id": "d1a", "created_at": _at(1, 8)},
        {"id": "d1b", "created_at": _at(1, 18)},
        {"id": "d2", "created_at": _at(2)},
        {"id": "d3", "created_at": _at(3)},
        {"id": "d4", "created_at": _at(4)},
    ]
    doomed = plan_prune(backups, keep_daily=2, keep_monthly=1, enabled=True)
    # Newest two days are 4 and 3. January's newest is d4, already kept.
    # d1b is the newest of day 1 but outside the daily window and the month
    # is already represented by d4, so d1a, d1b and d2 go.
    assert doomed == ["d2", "d1b", "d1a"]


def test_monthly_keeps_an_older_month_outside_the_daily_window():
    backups = [
        {"id": "jan", "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc)},
        {"id": "feb", "created_at": datetime(2026, 2, 15, tzinfo=timezone.utc)},
        {"id": "mar", "created_at": datetime(2026, 3, 15, tzinfo=timezone.utc)},
    ]
    doomed = plan_prune(backups, keep_daily=1, keep_monthly=2, enabled=True)
    assert doomed == ["jan"]


def test_disabled_or_zero_counts_delete_nothing():
    backups = [{"id": "only", "created_at": _at(1)}]
    assert plan_prune(backups, keep_daily=7, keep_monthly=6, enabled=False) == []
    assert plan_prune(backups, keep_daily=0, keep_monthly=0, enabled=True) == []


def test_policy_override_is_per_connection():
    settings = {
        "retention": {
            "enabled": True,
            "keep_daily": 7,
            "keep_monthly": 6,
            "connections": {
                "other": {"enabled": False, "keep_daily": 1, "keep_monthly": 0}
            },
        }
    }
    assert policy_for(settings, "main")["enabled"] is True
    assert policy_for(settings, "other")["enabled"] is False
    assert policy_for({}, "main")["enabled"] is False


class _Adapter:
    def __init__(self, backups):
        self.backups = list(backups)

    async def list_backups(self):
        return list(self.backups)

    async def delete_backup(self, backup_id: str) -> None:
        self.backups = [b for b in self.backups if b.id != backup_id]


def test_prune_connection_ignores_other_connections():
    adapter = _Adapter(
        [
            _info("keep", _at(4), "c1"),
            _info("drop", _at(1), "c1"),
            _info("other", _at(1), "c2"),
        ]
    )
    outcome = asyncio.run(
        prune_connection(
            adapter,
            "c1",
            {"enabled": True, "keep_daily": 1, "keep_monthly": 0},
        )
    )
    assert outcome["deleted"] == ["drop"]
    assert {b.id for b in adapter.backups} == {"keep", "other"}
