"""Keep-N daily / keep-M monthly pruning for backup copies.

The planner is pure. Deletion runs only for Local, Proton Drive and S3, only
after a scheduled backup succeeded, and only when a saved policy is enabled.
Google Drive is skipped: that adapter is not offered in the UI. A policy with
both counts at zero deletes nothing, so enabling the switch cannot wipe the
archive by accident. Timestamps that already carry a timezone are grouped on
their UTC calendar day; naive timestamps are grouped on the calendar date the
adapter stored (local backups use ``datetime.now()``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

PRUNE_ADAPTERS = frozenset({"local", "protondrive", "s3"})


def _stamp(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value


def plan_prune(
    backups: Sequence[Mapping[str, Any]],
    *,
    keep_daily: int,
    keep_monthly: int,
    enabled: bool = True,
) -> List[str]:
    """Return backup ids to delete.

    ``backups`` items need ``id`` and ``created_at`` (a ``datetime``). The
    newest copy of each calendar day covers the daily rule. The newest copy
    of each calendar month covers the monthly rule. A copy kept by either
    rule stays. ``enabled`` false, or both counts below 1, returns an empty
    list.
    """
    daily = int(keep_daily)
    monthly = int(keep_monthly)
    if not enabled or (daily < 1 and monthly < 1):
        return []

    rows = []
    for item in backups:
        created = item.get("created_at")
        ident = item.get("id")
        if not ident or not isinstance(created, datetime):
            continue
        rows.append((str(ident), _stamp(created)))
    rows.sort(key=lambda pair: pair[1], reverse=True)

    kept = set()
    if daily >= 1:
        seen_days = []
        newest_of_day = {}
        for ident, created in rows:
            day = created.date()
            if day not in newest_of_day:
                newest_of_day[day] = ident
                seen_days.append(day)
        for day in seen_days[:daily]:
            kept.add(newest_of_day[day])
    if monthly >= 1:
        seen_months = []
        newest_of_month = {}
        for ident, created in rows:
            month = (created.year, created.month)
            if month not in newest_of_month:
                newest_of_month[month] = ident
                seen_months.append(month)
        for month in seen_months[:monthly]:
            kept.add(newest_of_month[month])

    return [ident for ident, _created in rows if ident not in kept]


def policy_for(settings: Mapping[str, Any], connection_id: str) -> Dict[str, Any]:
    """Default retention, replaced by ``retention.connections[id]`` when set."""
    raw = settings.get("retention") if isinstance(settings, Mapping) else None
    if not isinstance(raw, dict):
        raw = {}
    policy = {
        "enabled": bool(raw.get("enabled", False)),
        "keep_daily": int(raw.get("keep_daily") or 0),
        "keep_monthly": int(raw.get("keep_monthly") or 0),
    }
    overrides = raw.get("connections") or {}
    override = overrides.get(connection_id) if isinstance(overrides, dict) else None
    if isinstance(override, dict):
        policy = {
            "enabled": bool(override.get("enabled", False)),
            "keep_daily": int(override.get("keep_daily") or 0),
            "keep_monthly": int(override.get("keep_monthly") or 0),
        }
    return policy


async def prune_connection(adapter: Any, connection_id: str, policy: Mapping[str, Any]) -> Dict[str, Any]:
    """Delete this connection's expired copies on ``adapter``. Never raises."""
    if not policy.get("enabled"):
        return {"deleted": [], "errors": [], "skipped": "disabled"}
    try:
        listed = await adapter.list_backups()
    except Exception as exc:  # noqa: BLE001 - prune must not fail the backup
        logger.warning("Retention could not list backups: %s", exc)
        return {"deleted": [], "errors": [{"id": "", "error": str(exc)}], "skipped": "list_failed"}

    mine = []
    for backup in listed:
        meta = getattr(backup, "metadata", None) or {}
        if str(meta.get("connectionId") or "") != str(connection_id):
            continue
        mine.append({"id": backup.id, "created_at": backup.createdAt})
    doomed = plan_prune(
        mine,
        keep_daily=int(policy.get("keep_daily") or 0),
        keep_monthly=int(policy.get("keep_monthly") or 0),
        enabled=True,
    )
    deleted: List[str] = []
    errors: List[Dict[str, str]] = []
    for backup_id in doomed:
        try:
            await adapter.delete_backup(backup_id)
            deleted.append(backup_id)
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": backup_id, "error": str(exc)})
    return {"deleted": deleted, "errors": errors, "skipped": None}


async def prune_scheduled(
    adapter: Any,
    adapter_type: str,
    results: Iterable[Mapping[str, Any]],
    store: Any,
) -> List[Dict[str, Any]]:
    """Prune each connection that just finished a scheduled backup."""
    if adapter_type not in PRUNE_ADAPTERS:
        return []
    try:
        settings = store.get_settings()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retention could not read settings: %s", exc)
        return []

    from ..audit import write_audit

    reports = []
    seen = set()
    for row in results:
        if row.get("status") != "completed":
            continue
        connection_id = row.get("connectionId")
        if not connection_id or connection_id in seen:
            continue
        seen.add(connection_id)
        policy = policy_for(settings, str(connection_id))
        outcome = await prune_connection(adapter, str(connection_id), policy)
        if outcome["deleted"] or outcome["errors"]:
            write_audit(
                "backup.retention_prune",
                "ok" if not outcome["errors"] else "error",
                connection_id=str(connection_id),
                adapter=adapter_type,
                deleted=len(outcome["deleted"]),
                errors=len(outcome["errors"]),
            )
        reports.append({"connection_id": connection_id, **outcome})
    return reports
