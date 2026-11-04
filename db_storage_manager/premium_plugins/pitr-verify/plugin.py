"""PITR Verify — first-party premium plugin.

Confirms point-in-time recovery for a PostgreSQL connection:

* Self-hosted: ``wal_level``, ``archive_mode``, ``archive_command`` /
  ``archive_library`` and ``pg_stat_archiver`` (PostgreSQL continuous
  archiving). The catalog does not expose how long archived WAL is kept, so
  a retention comparison is reported as not available rather than guessed.
* Managed Postgres, when the connection ``extra`` names a provider and
  instance and the operator's own credentials are configured (nothing is
  bundled): AWS RDS / Aurora PostgreSQL, Cloud SQL, Azure Database for
  PostgreSQL flexible server, Supabase, Neon.

Install requires ``plugins:manage`` (the Plugins tab). Running requires
``monitoring:read``. A missing privilege or a provider 401/403 is
``not_available`` — the plugin does not treat that as "PITR is off".

LicenseChain products for this plugin already exist; ``plugin.json``
``license.product_id`` is the monthly product
(``plugins.pricing.PREMIUM_PRODUCT_IDS["pitr-verify"]["monthly"]``).
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "pitr-verify"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"

# PostgreSQL continuous archiving. archive_library exists from PostgreSQL 15;
# older servers simply return no row for that name.
_SETTINGS_SQL = """
SELECT name, setting
FROM pg_catalog.pg_settings
WHERE name IN (
    'archive_mode',
    'archive_command',
    'archive_library',
    'archive_timeout',
    'wal_level',
    'server_version_num'
)
"""

_ARCHIVER_SQL = """
SELECT
    archived_count,
    last_archived_wal,
    last_archived_time,
    failed_count,
    last_failed_wal,
    last_failed_time,
    stats_reset
FROM pg_catalog.pg_stat_archiver
"""

# archive_command values PostgreSQL documents as "succeed without archiving".
_NOOP_ARCHIVE_COMMANDS = frozenset(
    {"true", "/bin/true", ":", "rem", "cmd /c rem"}
)

_AZURE_FLEX_API = "2026-10-01"
_DAY_SECONDS = 86400.0


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="PITR Verify",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Confirm PostgreSQL point-in-time recovery is enabled and "
            "that the configured retention matches the restorable window"
        ),
        plugin_type=PluginType.PERFORMANCE_MONITORING,
        plugin_id=PLUGIN_ID,
    )


def _iso(value: Any) -> Optional[str]:
    moment = _as_datetime(value)
    if moment is None:
        return None
    return moment.isoformat()


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10**12:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _window_days(earliest: Any, latest: Any) -> Optional[float]:
    start = _as_datetime(earliest)
    end = _as_datetime(latest)
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return seconds / _DAY_SECONDS


def _matches(
    actual: Optional[float], expected: Optional[float]
) -> Optional[bool]:
    """True when two retention lengths are the same instant, within 2 seconds."""
    if expected is None or actual is None:
        return None
    return abs(float(actual) - float(expected)) < (2 / _DAY_SECONDS)


def _public_error(exc: BaseException, secret: Optional[str] = None) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    if secret:
        text = text.replace(secret, "***")
    return text


def _safe_token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or any(ch in text for ch in "/\\?#&\n\r\t ") or ".." in text:
        raise ValueError(f"{label} is missing or contains invalid characters")
    return text


def finish_report(
    *,
    source: Optional[str],
    engine: Optional[str],
    pitr_enabled: Optional[bool],
    retention_days: Optional[float],
    window_days: Optional[float],
    expected_retention_days: Optional[float],
    earliest: Any = None,
    latest: Any = None,
    checks: Optional[List[Dict[str, Any]]] = None,
    reason: Optional[str] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the stable report and decide ok / fail / not_available."""
    checks = list(checks or [])
    expected = expected_retention_days
    matches = _matches(retention_days, expected)
    wants_off = (
        expected is not None and float(expected) == 0 and pitr_enabled is False
    )
    if wants_off:
        matches = True
    elif (
        pitr_enabled is False and expected is not None and float(expected) > 0
    ):
        matches = False

    fatal = next(
        (item for item in checks if item.get("fatal") and not item.get("ok")),
        None,
    )
    if pitr_enabled is None:
        status = "not_available"
    elif wants_off:
        status = "ok"
        reason = None
    elif pitr_enabled is False:
        status = "fail"
        reason = reason or "Point-in-time recovery is not enabled"
    elif fatal is not None:
        status = "fail"
        reason = reason or fatal.get("detail")
    elif expected is not None and matches is None:
        status = "not_available"
        reason = (
            reason
            or "This source does not report the PITR retention window, "
            "so it cannot be compared with the expected retention"
        )
    elif matches is False:
        status = "fail"
        reason = (
            f"Configured retention is {retention_days} days; "
            f"expected {expected} days"
        )
    else:
        status = "ok"
        reason = None

    return {
        "status": status,
        "plugin_id": PLUGIN_ID,
        "engine": engine,
        "source": source,
        "pitr_enabled": pitr_enabled,
        "retention_days": retention_days,
        "window_days": window_days,
        "expected_retention_days": expected_retention_days,
        "retention_matches": matches,
        "earliest_restorable_time": _iso(earliest),
        "latest_restorable_time": _iso(latest),
        "checks": checks,
        "reason": reason,
        "catalog": catalog,
        "permission": RUN_PERMISSION,
    }


def _check(
    name: str, ok: bool, detail: str, *, fatal: bool = False
) -> Dict[str, Any]:
    item: Dict[str, Any] = {"name": name, "ok": ok, "detail": detail}
    if fatal:
        item["fatal"] = True
    return item


def _archive_target(settings: Dict[str, str]) -> tuple[bool, str]:
    library = (settings.get("archive_library") or "").strip()
    command = (settings.get("archive_command") or "").strip()
    if library:
        return True, f"archive_library={library}"
    if not command or command == "(disabled)":
        return False, "archive_command is not set"
    return True, f"archive_command={command}"


def interpret_catalog(
    settings_rows: List[Dict[str, Any]],
    archiver_row: Optional[Dict[str, Any]],
    *,
    expected_retention_days: Optional[float] = None,
    engine: str = "postgresql",
) -> Dict[str, Any]:
    """Decide PITR from ``pg_settings`` and one ``pg_stat_archiver`` row."""
    settings = {
        str(row["name"]): (
            "" if row.get("setting") is None else str(row["setting"])
        )
        for row in settings_rows
        if row.get("name")
    }
    if "archive_mode" not in settings or "wal_level" not in settings:
        return finish_report(
            source="pg_stat_archiver",
            engine=engine,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "pg_settings did not return archive_mode and wal_level; "
                "PITR was not guessed"
            ),
            catalog={
                "settings": settings,
                "archiver": _jsonable(archiver_row),
            },
        )
    if not archiver_row:
        return finish_report(
            source="pg_stat_archiver",
            engine=engine,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason="pg_stat_archiver returned no row; PITR was not guessed",
            catalog={"settings": settings, "archiver": None},
        )

    wal = settings.get("wal_level", "")
    mode = settings.get("archive_mode", "")
    target_ok, target_detail = _archive_target(settings)
    wal_ok = wal in ("replica", "logical")
    mode_ok = mode in ("on", "always")
    enabled = wal_ok and mode_ok and target_ok
    checks = [
        _check("wal_level", wal_ok, wal or "(empty)"),
        _check("archive_mode", mode_ok, mode or "(empty)"),
        _check("archive_target", target_ok, target_detail),
    ]
    command = (settings.get("archive_command") or "").strip().lower()
    if enabled and command in _NOOP_ARCHIVE_COMMANDS:
        checks.append(
            _check(
                "archive_command",
                False,
                "archive_command returns success without storing WAL, "
                "which breaks the archive needed for point-in-time recovery",
                fatal=True,
            )
        )

    last_failed = _as_datetime(archiver_row.get("last_failed_time"))
    last_ok = _as_datetime(archiver_row.get("last_archived_time"))
    if (
        enabled
        and last_failed is not None
        and (last_ok is None or last_failed > last_ok)
    ):
        checks.append(
            _check(
                "pg_stat_archiver",
                False,
                "The latest pg_stat_archiver attempt failed "
                f"({archiver_row.get('last_failed_wal')})",
                fatal=True,
            )
        )
    else:
        checks.append(
            _check(
                "pg_stat_archiver",
                True,
                "archived_count="
                f"{archiver_row.get('archived_count')} "
                "failed_count="
                f"{archiver_row.get('failed_count')}",
            )
        )

    reason = None
    if not enabled:
        reason = (
            "Continuous archiving is not configured "
            f"(wal_level={wal or 'unknown'}, archive_mode={mode or 'unknown'}, "
            f"{target_detail})"
        )
    return finish_report(
        source="pg_stat_archiver",
        engine=engine,
        pitr_enabled=enabled,
        retention_days=None,
        window_days=None,
        expected_retention_days=expected_retention_days,
        checks=checks,
        reason=reason,
        catalog={
            "settings": settings,
            "archiver": _jsonable(archiver_row),
        },
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def interpret_rds_instance(
    instance: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpret one RDS ``DBInstance`` (DescribeDBInstances)."""
    engine = str(instance.get("Engine") or "")
    if engine.startswith("aurora"):
        return finish_report(
            source="aws_rds",
            engine="postgresql" if "postgres" in engine else engine,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Aurora retention is on the DB cluster "
                "(DescribeDBClusters EarliestRestorableTime / "
                "BackupRetentionPeriod), not on the DB instance"
            ),
        )
    if engine not in ("postgres", ""):
        return finish_report(
            source="aws_rds",
            engine=engine or None,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                f"RDS engine {engine or 'unknown'} is not PostgreSQL; "
                "PITR was not guessed"
            ),
        )
    if "BackupRetentionPeriod" not in instance:
        return finish_report(
            source="aws_rds",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "DescribeDBInstances did not return BackupRetentionPeriod; "
                "PITR was not guessed"
            ),
        )
    days = float(instance["BackupRetentionPeriod"])
    earliest = instance.get("EarliestRestorableTime")
    latest = instance.get("LatestRestorableTime")
    enabled = days > 0
    detail = (
        f"BackupRetentionPeriod={int(days)} "
        "(RDS DBInstance has LatestRestorableTime; "
        "EarliestRestorableTime is a cluster field)"
    )
    return finish_report(
        source="aws_rds",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=days,
        window_days=_window_days(earliest, latest),
        expected_retention_days=expected_retention_days,
        earliest=earliest,
        latest=latest,
        checks=[_check("BackupRetentionPeriod", enabled, detail)],
        reason=(
            None
            if enabled
            else "RDS automated backups are disabled (BackupRetentionPeriod is 0)"
        ),
    )


def interpret_rds_cluster(
    cluster: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpret one Aurora ``DBCluster`` (DescribeDBClusters)."""
    engine = str(cluster.get("Engine") or "")
    if engine and engine != "aurora-postgresql":
        return finish_report(
            source="aws_aurora",
            engine=engine,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                f"DB cluster engine {engine} is not aurora-postgresql; "
                "PITR was not guessed"
            ),
        )
    if "BackupRetentionPeriod" not in cluster:
        return finish_report(
            source="aws_aurora",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "DescribeDBClusters did not return BackupRetentionPeriod; "
                "PITR was not guessed"
            ),
        )
    days = float(cluster["BackupRetentionPeriod"])
    earliest = cluster.get("EarliestRestorableTime")
    latest = cluster.get("LatestRestorableTime")
    enabled = days > 0 and earliest is not None
    if days > 0 and earliest is None:
        return finish_report(
            source="aws_aurora",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=days,
            window_days=None,
            expected_retention_days=expected_retention_days,
            latest=latest,
            checks=[
                _check(
                    "EarliestRestorableTime",
                    False,
                    "BackupRetentionPeriod is set but EarliestRestorableTime "
                    "is absent, so the restorable window is unknown",
                )
            ],
            reason=(
                "Aurora did not return EarliestRestorableTime; "
                "PITR was not guessed"
            ),
        )
    return finish_report(
        source="aws_aurora",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=days,
        window_days=_window_days(earliest, latest),
        expected_retention_days=expected_retention_days,
        earliest=earliest,
        latest=latest,
        checks=[
            _check(
                "BackupRetentionPeriod",
                enabled,
                f"BackupRetentionPeriod={int(days)}",
            )
        ],
        reason=(
            None
            if enabled
            else "Aurora automated backups are disabled (BackupRetentionPeriod is 0)"
        ),
    )


def interpret_cloudsql(
    instance: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpret a Cloud SQL Admin API instance resource."""
    version = str(instance.get("databaseVersion") or "")
    if version and "POSTGRES" not in version.upper():
        return finish_report(
            source="gcp_cloudsql",
            engine=version,
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                f"Cloud SQL databaseVersion {version} is not PostgreSQL; "
                "PITR was not guessed"
            ),
        )
    backup = (instance.get("settings") or {}).get("backupConfiguration") or {}
    if "pointInTimeRecoveryEnabled" not in backup:
        return finish_report(
            source="gcp_cloudsql",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Cloud SQL did not return "
                "settings.backupConfiguration.pointInTimeRecoveryEnabled; "
                "PITR was not guessed"
            ),
        )
    enabled = bool(backup.get("pointInTimeRecoveryEnabled"))
    days = backup.get("transactionLogRetentionDays")
    retention = (
        float(days)
        if enabled and days is not None
        else (0.0 if not enabled else None)
    )
    if enabled and days is None:
        return finish_report(
            source="gcp_cloudsql",
            engine="postgresql",
            pitr_enabled=True,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            checks=[
                _check(
                    "pointInTimeRecoveryEnabled",
                    True,
                    "pointInTimeRecoveryEnabled is true but "
                    "transactionLogRetentionDays is absent",
                )
            ],
            reason=(
                "Cloud SQL did not return transactionLogRetentionDays; "
                "the PITR window cannot be compared"
            ),
        )
    return finish_report(
        source="gcp_cloudsql",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=retention,
        window_days=None,
        expected_retention_days=expected_retention_days,
        checks=[
            _check(
                "pointInTimeRecoveryEnabled",
                enabled,
                f"pointInTimeRecoveryEnabled={enabled} "
                f"transactionLogRetentionDays={days}",
            )
        ],
        reason=(
            None if enabled else "Cloud SQL point-in-time recovery is disabled"
        ),
    )


def interpret_azure_flexible(
    server: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Interpret an Azure Database for PostgreSQL flexible server."""
    backup = (server.get("properties") or {}).get("backup") or {}
    if "backupRetentionDays" not in backup:
        return finish_report(
            source="azure_postgres",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Azure flexible server did not return "
                "properties.backup.backupRetentionDays; PITR was not guessed"
            ),
        )
    days = float(backup["backupRetentionDays"])
    earliest = backup.get("earliestRestoreDate")
    latest = now or datetime.now(timezone.utc)
    enabled = days > 0 and earliest is not None
    if days > 0 and earliest is None:
        return finish_report(
            source="azure_postgres",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=days,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Azure flexible server did not return earliestRestoreDate; "
                "PITR was not guessed"
            ),
        )
    return finish_report(
        source="azure_postgres",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=days,
        window_days=_window_days(earliest, latest) if enabled else None,
        expected_retention_days=expected_retention_days,
        earliest=earliest,
        latest=latest if enabled else None,
        checks=[
            _check(
                "backupRetentionDays",
                enabled,
                f"backupRetentionDays={int(days)}",
            )
        ],
        reason=(
            None
            if enabled
            else "Azure flexible server backup retention is 0 days"
        ),
    )


def interpret_supabase(
    payload: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpret ``GET /v1/projects/{ref}/database/backups``."""
    if "pitr_enabled" not in payload:
        return finish_report(
            source="supabase",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Supabase backups response has no pitr_enabled; "
                "PITR was not guessed"
            ),
        )
    enabled = bool(payload.get("pitr_enabled"))
    physical = payload.get("physical_backup_data") or {}
    earliest = physical.get("earliest_physical_backup_date_unix")
    latest = physical.get("latest_physical_backup_date_unix")
    # The backups API does not return the PITR add-on length (7/14/28 days).
    # Physical backup timestamps are not that retention, so retention_days
    # stays unknown.
    return finish_report(
        source="supabase",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=None,
        window_days=_window_days(earliest, latest),
        expected_retention_days=expected_retention_days,
        earliest=earliest,
        latest=latest,
        checks=[
            _check(
                "pitr_enabled",
                enabled,
                "Supabase reports pitr_enabled but not the add-on "
                "retention in days",
            )
        ],
        reason=(
            None if enabled else "Supabase point-in-time recovery is disabled"
        ),
    )


def interpret_neon(
    payload: Dict[str, Any],
    *,
    expected_retention_days: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpret ``GET /api/v2/projects/{project_id}`` history retention."""
    project = (
        payload.get("project")
        if isinstance(payload.get("project"), dict)
        else payload
    )
    if "history_retention_seconds" not in project:
        return finish_report(
            source="neon",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                "Neon project has no history_retention_seconds; "
                "PITR was not guessed"
            ),
        )
    seconds = int(project["history_retention_seconds"])
    enabled = seconds > 0
    days = seconds / _DAY_SECONDS
    return finish_report(
        source="neon",
        engine="postgresql",
        pitr_enabled=enabled,
        retention_days=days,
        window_days=days if enabled else 0.0,
        expected_retention_days=expected_retention_days,
        checks=[
            _check(
                "history_retention_seconds",
                enabled,
                f"history_retention_seconds={seconds}",
            )
        ],
        reason=(
            None
            if enabled
            else "Neon history retention is 0 (instant restore is off)"
        ),
    )


def combine_reports(
    catalog: Dict[str, Any], provider: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Provider retention wins. A provider that cannot be read is not replaced
    by a catalog guess about a managed window."""
    if provider is None:
        return catalog
    checks = list(provider.get("checks") or [])
    for item in catalog.get("checks") or []:
        named = dict(item)
        named["name"] = f"catalog.{item.get('name')}"
        checks.append(named)
    if (
        provider.get("status") == "not_available"
        and provider.get("pitr_enabled") is None
    ):
        merged = dict(provider)
        merged["checks"] = checks
        merged["catalog"] = catalog.get("catalog")
        return merged
    merged = dict(provider)
    merged["checks"] = checks
    merged["catalog"] = catalog.get("catalog")
    return merged


def _unavailable(
    engine: Optional[str], reason: str, *, source: Optional[str] = None
) -> Dict[str, Any]:
    return finish_report(
        source=source,
        engine=engine,
        pitr_enabled=None,
        retention_days=None,
        window_days=None,
        expected_retention_days=None,
        reason=reason,
    )


def _engine_name(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    raw = getattr(config, "type", None)
    if raw is None and isinstance(connection, dict):
        raw = connection.get("type")
    if not isinstance(raw, str) or not raw.strip():
        return None
    name = raw.strip().lower()
    if name == "postgres":
        return "postgresql"
    return name


def _extra(connection: Any) -> Dict[str, Any]:
    config = getattr(connection, "config", None)
    extra = getattr(config, "extra", None)
    if isinstance(extra, dict):
        return extra
    return {}


def _expected_days(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected_retention_days must be a number of days")
    days = float(value)
    if days < 0:
        raise ValueError("expected_retention_days must be >= 0")
    return days


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _postgres_raw(connection: Any) -> Any:
    raw = getattr(connection, "connection", None)
    if raw is not None and hasattr(raw, "get_transaction_status"):
        return raw
    if hasattr(connection, "get_transaction_status"):
        return connection
    if hasattr(connection, "connect"):
        _run_async(connection.connect())
        raw = getattr(connection, "connection", None)
        if raw is not None and hasattr(raw, "get_transaction_status"):
            return raw
    raise RuntimeError("PostgreSQL connection is not open")


def _is_privilege(exc: BaseException) -> bool:
    if getattr(exc, "pgcode", None) == "42501":
        return True
    text = str(exc).lower()
    return "permission denied" in text or "must be superuser" in text


def _query(raw: Any, sql: str) -> List[Dict[str, Any]]:
    from psycopg2.extensions import (
        TRANSACTION_STATUS_IDLE,
        TRANSACTION_STATUS_INERROR,
    )
    from psycopg2.extras import RealDictCursor

    status = raw.get_transaction_status()
    if status == TRANSACTION_STATUS_INERROR:
        raw.rollback()
        status = TRANSACTION_STATUS_IDLE
    cursor = raw.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
    if status == TRANSACTION_STATUS_IDLE:
        raw.rollback()
    return rows


def read_catalog(connection: Any) -> Dict[str, Any]:
    """Read ``pg_settings`` and ``pg_stat_archiver`` from a live PostgreSQL."""
    secret = getattr(getattr(connection, "config", None), "password", None)
    try:
        raw = _postgres_raw(connection)
        settings = _query(raw, _SETTINGS_SQL)
        archiver_rows = _query(raw, _ARCHIVER_SQL)
    except Exception as exc:
        if _is_privilege(exc):
            return _unavailable(
                "postgresql",
                "Not available on this role: "
                + _public_error(exc, secret)
                + ". PITR was not guessed.",
                source="pg_stat_archiver",
            )
        return _unavailable(
            "postgresql",
            "PostgreSQL catalog could not be read: "
            + _public_error(exc, secret),
            source="pg_stat_archiver",
        )
    archiver = archiver_rows[0] if archiver_rows else None
    return {"settings": settings, "archiver": archiver}


def _http_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        if exc.code in (401, 403):
            raise PermissionError(
                f"HTTP {exc.code} from {url.split('?', 1)[0]}: "
                "not available on this plan or role. " + detail
            ) from exc
        raise RuntimeError(
            f"HTTP {exc.code} from {url.split('?', 1)[0]}: {detail}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("provider response was not a JSON object")
    return parsed


def _env_secret(*names: str) -> Optional[str]:
    import os

    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _provider_key(extra: Dict[str, Any]) -> str:
    return str(extra.get("cloud_provider") or "").strip().lower()


def fetch_provider(
    extra: Dict[str, Any],
    *,
    expected_retention_days: Optional[float],
) -> Dict[str, Any]:
    """Call the managed-Postgres API named on the connection. No bundled secrets."""
    provider = _provider_key(extra)
    try:
        instance_id = extra.get("cloud_instance_id") or extra.get(
            "instance_id"
        )
        if provider in ("aws_rds", "aws", "rds"):
            return _fetch_aws(extra, instance_id, expected_retention_days)
        if provider in ("gcp_cloudsql", "gcp", "cloudsql"):
            return _fetch_cloudsql(instance_id, expected_retention_days)
        if provider in (
            "azure_postgres",
            "azure_flexible",
            "azure_db_for_postgresql",
        ):
            return _fetch_azure(extra, instance_id, expected_retention_days)
        if provider == "supabase":
            return _fetch_supabase(extra, instance_id, expected_retention_days)
        if provider == "neon":
            return _fetch_neon(extra, instance_id, expected_retention_days)
        if provider in ("azure_sql", "azure"):
            return finish_report(
                source="azure_sql",
                engine="sqlserver",
                pitr_enabled=None,
                retention_days=None,
                window_days=None,
                expected_retention_days=expected_retention_days,
                reason=(
                    "cloud_provider azure_sql is Azure SQL (SQL Server). "
                    "PostgreSQL PITR uses cloud_provider azure_postgres "
                    "(flexible server). PITR was not guessed."
                ),
            )
        return finish_report(
            source=provider or None,
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                f"No PITR API is implemented for cloud_provider {provider!r}. "
                "PITR was not guessed from the name."
            ),
        )
    except PermissionError as exc:
        return finish_report(
            source=provider,
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=str(exc),
        )
    except Exception as exc:
        return finish_report(
            source=provider,
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected_retention_days,
            reason=(
                f"{provider} PITR API could not be read: {_public_error(exc)}. "
                "PITR was not guessed."
            ),
        )


def _fetch_aws(
    extra: Dict[str, Any],
    instance_id: Any,
    expected: Optional[float],
) -> Dict[str, Any]:
    ident = _safe_token(instance_id, "cloud_instance_id")
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
    )

    from db_storage_manager.cloud.aws import AWSRDSProvider

    region = extra.get("aws_region") or extra.get("region")
    provider = AWSRDSProvider(region=str(region) if region else "us-east-1")
    try:
        response = provider.rds_client.describe_db_instances(
            DBInstanceIdentifier=ident
        )
    except NoCredentialsError as exc:
        raise RuntimeError(
            "AWS credentials are not configured (no keys, profile, or "
            "default chain). No credentials are bundled with the plugin."
        ) from exc
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("AccessDenied", "UnauthorizedOperation", "NotAuthorized"):
            raise PermissionError(
                f"AWS RDS {code}: not available on this plan or role"
            ) from exc
        raise RuntimeError(f"AWS RDS {code or 'error'}: {exc}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"AWS RDS client error: {exc}") from exc

    instances = response.get("DBInstances") or []
    if not instances:
        return finish_report(
            source="aws_rds",
            engine="postgresql",
            pitr_enabled=None,
            retention_days=None,
            window_days=None,
            expected_retention_days=expected,
            reason=f"RDS instance {ident} was not found",
        )
    instance = instances[0]
    engine = str(instance.get("Engine") or "")
    if engine.startswith("aurora"):
        cluster_id = instance.get("DBClusterIdentifier")
        if not cluster_id:
            return finish_report(
                source="aws_aurora",
                engine="postgresql",
                pitr_enabled=None,
                retention_days=None,
                window_days=None,
                expected_retention_days=expected,
                reason="Aurora instance has no DBClusterIdentifier",
            )
        clusters = provider.rds_client.describe_db_clusters(
            DBClusterIdentifier=cluster_id
        )
        found = clusters.get("DBClusters") or []
        if not found:
            return finish_report(
                source="aws_aurora",
                engine="postgresql",
                pitr_enabled=None,
                retention_days=None,
                window_days=None,
                expected_retention_days=expected,
                reason=f"Aurora cluster {cluster_id} was not found",
            )
        return interpret_rds_cluster(
            found[0], expected_retention_days=expected
        )
    return interpret_rds_instance(instance, expected_retention_days=expected)


def _fetch_cloudsql(
    instance_id: Any, expected: Optional[float]
) -> Dict[str, Any]:
    name = _safe_token(instance_id, "cloud_instance_id")
    from db_storage_manager.cloud.credentials import (
        require_gcp,
        resolve_cloud_config,
    )

    cfg = require_gcp(resolve_cloud_config())
    project = cfg["project_id"]
    credentials_path = cfg.get("credentials_path")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    if credentials_path:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
    else:
        from google.auth import default as google_auth_default

        credentials, _ = google_auth_default(scopes=scopes)
    from googleapiclient import discovery

    service = discovery.build(
        "sqladmin", "v1", credentials=credentials, cache_discovery=False
    )
    instance = (
        service.instances().get(project=project, instance=name).execute()
    )
    if not isinstance(instance, dict):
        raise RuntimeError("Cloud SQL instances.get did not return an object")
    return interpret_cloudsql(instance, expected_retention_days=expected)


def _fetch_azure(
    extra: Dict[str, Any],
    instance_id: Any,
    expected: Optional[float],
) -> Dict[str, Any]:
    server = _safe_token(instance_id, "cloud_instance_id")
    group = _safe_token(extra.get("resource_group"), "resource_group")
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            'azure-identity is not installed (pip install -e ".[azure]"). '
            "PITR was not guessed."
        ) from exc
    from db_storage_manager.cloud.credentials import (
        require_azure,
        resolve_cloud_config,
    )

    cfg = require_azure(resolve_cloud_config())
    token = (
        DefaultAzureCredential()
        .get_token("https://management.azure.com/.default")
        .token
    )
    subscription = _safe_token(cfg.get("subscription_id"), "subscription_id")
    url = (
        "https://management.azure.com/subscriptions/"
        f"{subscription}/resourceGroups/{group}/providers/"
        "Microsoft.DBforPostgreSQL/flexibleServers/"
        f"{server}?api-version={_AZURE_FLEX_API}"
    )
    payload = _http_json(url, {"Authorization": f"Bearer {token}"})
    return interpret_azure_flexible(payload, expected_retention_days=expected)


def _fetch_supabase(
    extra: Dict[str, Any],
    instance_id: Any,
    expected: Optional[float],
) -> Dict[str, Any]:
    ref = _safe_token(
        instance_id or extra.get("supabase_project_ref"), "cloud_instance_id"
    )
    token = _env_secret("DSM_SUPABASE_ACCESS_TOKEN", "SUPABASE_ACCESS_TOKEN")
    if not token:
        token = extra.get("supabase_access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(
            "Supabase access token is not configured "
            "(DSM_SUPABASE_ACCESS_TOKEN). No token is bundled."
        )
    url = f"https://api.supabase.com/v1/projects/{ref}/database/backups"
    payload = _http_json(
        url,
        {
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/json",
        },
    )
    return interpret_supabase(payload, expected_retention_days=expected)


def _fetch_neon(
    extra: Dict[str, Any],
    instance_id: Any,
    expected: Optional[float],
) -> Dict[str, Any]:
    project_id = _safe_token(
        instance_id or extra.get("neon_project_id"), "cloud_instance_id"
    )
    token = _env_secret("DSM_NEON_API_KEY", "NEON_API_KEY")
    if not token:
        token = extra.get("neon_api_key")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(
            "Neon API key is not configured (NEON_API_KEY). No key is bundled."
        )
    url = f"https://console.neon.tech/api/v2/projects/{project_id}"
    payload = _http_json(
        url,
        {
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/json",
        },
    )
    return interpret_neon(payload, expected_retention_days=expected)


class PitrVerifyPlugin(Plugin):
    """Premium plugin: PostgreSQL PITR enabled, and retention when a source has it."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(
        self,
        connection: Any = None,
        expected_retention_days: Any = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        try:
            expected = _expected_days(expected_retention_days)
        except ValueError as exc:
            return _unavailable(None, str(exc))

        engine = _engine_name(connection)
        if connection is None or engine is None:
            return _unavailable(
                engine,
                "A database connection with a type is required",
            )
        if engine != "postgresql":
            return finish_report(
                source=None,
                engine=engine,
                pitr_enabled=None,
                retention_days=None,
                window_days=None,
                expected_retention_days=expected,
                reason=(
                    "PITR verify reads PostgreSQL pg_stat_archiver and "
                    "managed Postgres provider APIs. "
                    f"This connection is {engine}."
                ),
            )

        catalog_raw = read_catalog(connection)
        if "settings" not in catalog_raw:
            catalog_report = catalog_raw
        else:
            catalog_report = interpret_catalog(
                catalog_raw["settings"],
                catalog_raw.get("archiver"),
                expected_retention_days=expected,
                engine=engine,
            )

        extra = _extra(connection)
        provider = _provider_key(extra)
        if not provider:
            return catalog_report
        provider_report = fetch_provider(
            extra, expected_retention_days=expected
        )
        return combine_reports(catalog_report, provider_report)

    def cleanup(self) -> None:
        self._context = {}


PLUGIN_CLASS = PitrVerifyPlugin
