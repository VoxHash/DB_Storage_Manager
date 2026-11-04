"""Maintenance window and version end-of-life.

PostgreSQL dates are the Final Release column on
https://www.postgresql.org/support/versioning/ (read 2026-11-04). MySQL dates
are Oracle Lifetime Support as published on endoflife.date and the MySQL 8.0
release notes: 8.0 extended support ended 2026-04-30, 8.4 extended support
ends 2032-04-30, 9.7 extended support ends 2034-04-30. A version that is not
in those tables is ``not_available`` for end-of-life rather than treated as
supported. MariaDB is not compared to the MySQL calendar.

A version inside 90 days of its final date is ``ending``. A past date is
``eol``. DigitalOcean ``maintenance_window.pending`` and RDS
``PendingMaintenanceActions`` become alerts. A Neon ``maintenance_window`` is
reported as the project's schedule and is not an alert by itself.

The ``alerts`` list is the feed a caller can show. This plugin does not poll
a provider on a timer.

Install requires ``plugins:manage``. Running requires ``monitoring:read``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from db_storage_manager.plugins.sdk import Plugin, PluginMetadata, PluginType

PLUGIN_ID = "maintenance-window-watch"
RUN_PERMISSION = "monitoring:read"
INSTALL_PERMISSION = "plugins:manage"
_ENDING_DAYS = 90

# Final release dates, postgresql.org/support/versioning/.
POSTGRES_FINAL = {
    18: date(2030, 11, 14),
    17: date(2029, 11, 8),
    16: date(2028, 11, 9),
    15: date(2027, 11, 11),
    14: date(2026, 11, 12),
    13: date(2025, 11, 13),
    12: date(2024, 11, 21),
    11: date(2023, 11, 9),
    10: date(2022, 11, 10),
}

# Extended-support end. Innovation releases end when the next one ships.
MYSQL_FINAL = {
    (9, 7): date(2034, 4, 30),
    (8, 4): date(2032, 4, 30),
    (8, 0): date(2026, 4, 30),
    (5, 7): date(2023, 10, 31),
    (5, 6): date(2021, 2, 28),
    (9, 6): date(2026, 4, 21),
    (9, 5): date(2026, 1, 20),
    (9, 4): date(2025, 10, 21),
    (9, 3): date(2025, 7, 22),
    (9, 2): date(2025, 4, 15),
    (9, 1): date(2025, 1, 21),
    (9, 0): date(2024, 10, 15),
    (8, 3): date(2024, 4, 30),
    (8, 2): date(2024, 1, 16),
    (8, 1): date(2023, 10, 25),
}


def _metadata() -> PluginMetadata:
    return PluginMetadata(
        name="Maintenance window watch",
        version="1.0.0",
        author="VoxHash",
        description=(
            "Report provider maintenance and PostgreSQL or MySQL version "
            "end-of-life in an alerts list"
        ),
        plugin_type=PluginType.PERFORMANCE_MONITORING,
        plugin_id=PLUGIN_ID,
    )


def _engine_name(connection: Any) -> Optional[str]:
    config = getattr(connection, "config", None)
    raw = getattr(config, "type", None) if config is not None else None
    if raw is None and isinstance(connection, dict):
        raw = connection.get("type")
    if raw is None:
        return None
    name = str(raw).strip().lower()
    if name in {"postgres", "supabase"}:
        return "postgresql"
    if name == "mariadb":
        return "mariadb"
    return name


def parse_version(engine: str, version: str) -> Optional[Any]:
    text = str(version or "").strip()
    if not text:
        return None
    head = text.split()[0]
    parts = []
    for piece in head.replace("-", ".").split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    if engine == "postgresql" and parts:
        return parts[0]
    if engine == "mysql" and len(parts) >= 2:
        return (parts[0], parts[1])
    return None


def classify_eol(engine: str, version: str, today: date) -> Dict[str, Any]:
    """Community or Oracle end-of-life for one version string."""
    if engine == "mariadb":
        return {
            "status": "not_available",
            "reason": "MariaDB has its own support calendar. This check does not apply the MySQL dates.",
        }
    if engine not in {"postgresql", "mysql"}:
        return {
            "status": "not_available",
            "reason": "End-of-life dates are published here for PostgreSQL and MySQL.",
        }
    parsed = parse_version(engine, version)
    table = POSTGRES_FINAL if engine == "postgresql" else MYSQL_FINAL
    final = table.get(parsed) if parsed is not None else None
    if final is None:
        return {
            "status": "not_available",
            "reason": "This version is not in the published end-of-life table, so support was not guessed.",
            "version": version,
        }
    days = (final - today).days
    if days < 0:
        eol_status = "eol"
    elif days <= _ENDING_DAYS:
        eol_status = "ending"
    else:
        eol_status = "supported"
    return {
        "status": "fail" if eol_status in {"eol", "ending"} else "ok",
        "eol_status": eol_status,
        "eol_date": final.isoformat(),
        "days_remaining": days,
        "version": version,
        "source": (
            "https://www.postgresql.org/support/versioning/"
            if engine == "postgresql"
            else "Oracle MySQL Lifetime Support (extended support end)"
        ),
    }


def _alert(title: str, message: str, severity: str, source: str) -> Dict[str, str]:
    return {"title": title, "message": message, "severity": severity, "source": source}


def alerts_for_eol(engine: str, eol: Dict[str, Any]) -> List[Dict[str, str]]:
    if eol.get("eol_status") == "eol":
        return [
            _alert(
                f"{engine} {eol.get('version')} is end of life",
                f"The published final date was {eol.get('eol_date')}.",
                "critical",
                "maintenance",
            )
        ]
    if eol.get("eol_status") == "ending":
        return [
            _alert(
                f"{engine} {eol.get('version')} support ends soon",
                (
                    f"The published final date is {eol.get('eol_date')} "
                    f"({eol.get('days_remaining')} days)."
                ),
                "warning",
                "maintenance",
            )
        ]
    return []


def interpret_digitalocean_maintenance(database: Dict[str, Any]) -> Dict[str, Any]:
    window = database.get("maintenance_window") if isinstance(database, dict) else None
    window = window if isinstance(window, dict) else {}
    pending = bool(window.get("pending"))
    description = window.get("description") if isinstance(window.get("description"), list) else []
    provider_eol = database.get("version_end_of_life") if isinstance(database, dict) else None
    return {
        "provider": "digitalocean",
        "pending": pending,
        "day": window.get("day"),
        "hour": window.get("hour"),
        "description": [str(item) for item in description],
        "version_end_of_life": provider_eol,
    }


def interpret_aws_pending(payload: Any) -> List[Dict[str, Any]]:
    actions = []
    if isinstance(payload, dict):
        actions = payload.get("PendingMaintenanceActions") or payload.get("pending") or []
    found = []
    for group in actions if isinstance(actions, list) else []:
        if not isinstance(group, dict):
            continue
        details = group.get("PendingMaintenanceActionDetails") or group.get("details") or []
        if isinstance(details, dict):
            details = [details]
        for detail in details:
            if not isinstance(detail, dict):
                continue
            found.append(
                {
                    "action": detail.get("Action") or detail.get("action"),
                    "description": detail.get("Description") or detail.get("description"),
                    "apply_at": detail.get("CurrentApplyDate") or detail.get("apply_at"),
                }
            )
    return found


def interpret_neon_window(project: Any) -> Optional[Dict[str, Any]]:
    body = project.get("project") if isinstance(project, dict) and isinstance(project.get("project"), dict) else project
    settings = body.get("settings") if isinstance(body, dict) else None
    window = settings.get("maintenance_window") if isinstance(settings, dict) else None
    if not isinstance(window, dict):
        return None
    return {
        "provider": "neon",
        "weekdays": window.get("weekdays"),
        "start_time": window.get("start_time"),
        "end_time": window.get("end_time"),
    }


def build_report(
    *,
    engine: Optional[str],
    version: Optional[str],
    today: date,
    digitalocean: Optional[Dict[str, Any]] = None,
    aws_pending: Any = None,
    neon: Any = None,
) -> Dict[str, Any]:
    alerts: List[Dict[str, str]] = []
    eol: Optional[Dict[str, Any]] = None
    if engine and version:
        eol = classify_eol(engine, version, today)
        alerts.extend(alerts_for_eol(engine, eol))
    maintenance: List[Dict[str, Any]] = []
    if isinstance(digitalocean, dict):
        item = interpret_digitalocean_maintenance(digitalocean)
        maintenance.append(item)
        if item.get("pending"):
            detail = "; ".join(item.get("description") or []) or "Pending maintenance"
            alerts.append(
                _alert(
                    "DigitalOcean maintenance is pending",
                    detail,
                    "warning",
                    "maintenance",
                )
            )
        provider_eol = item.get("version_end_of_life")
        if isinstance(provider_eol, str) and provider_eol:
            alerts.append(
                _alert(
                    "DigitalOcean published a version end of life",
                    provider_eol,
                    "warning",
                    "maintenance",
                )
            )
    if aws_pending is not None:
        pending = interpret_aws_pending(aws_pending)
        if pending:
            maintenance.append({"provider": "aws", "pending": pending})
            alerts.append(
                _alert(
                    "RDS maintenance is pending",
                    f"{len(pending)} pending action(s).",
                    "warning",
                    "maintenance",
                )
            )
    if neon is not None:
        window = interpret_neon_window(neon)
        if window:
            maintenance.append(window)
    if eol and eol.get("status") == "not_available" and not alerts and not maintenance:
        status = "not_available"
    elif any(item["severity"] == "critical" for item in alerts) or (
        eol and eol.get("eol_status") == "eol"
    ):
        status = "fail"
    elif alerts:
        status = "fail"
    elif eol and eol.get("status") == "ok":
        status = "ok"
    elif maintenance or eol:
        status = "ok" if not alerts else "fail"
    else:
        status = "not_available"
    return {
        "ok": status == "ok",
        "status": status,
        "engine": engine,
        "version": version,
        "eol": eol,
        "maintenance": maintenance,
        "alerts": alerts,
        "permission": RUN_PERMISSION,
    }


class MaintenanceWindowPlugin(Plugin):
    """Premium plugin: maintenance windows and version end-of-life."""

    def __init__(self, metadata: Optional[PluginMetadata] = None):
        super().__init__(metadata or _metadata())

    def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    def execute(self, connection: Any = None, **kwargs: Any) -> Dict[str, Any]:
        from db_storage_manager.security.auth import get_auth_manager

        get_auth_manager().require(RUN_PERMISSION)
        engine = kwargs.get("engine") or _engine_name(connection)
        version = kwargs.get("version")
        if version is None and connection is not None and engine in {"postgresql", "mysql"}:
            version = _read_version(connection, engine)
        today = kwargs.get("today") or date.today()
        if isinstance(today, datetime):
            today = today.date()
        if isinstance(today, str):
            today = date.fromisoformat(today)
        payloads = kwargs.get("payloads") or {}
        return build_report(
            engine=engine,
            version=version,
            today=today,
            digitalocean=payloads.get("digitalocean"),
            aws_pending=payloads.get("aws"),
            neon=payloads.get("neon"),
        )

    def cleanup(self) -> None:
        self._context = {}


def _read_version(connection: Any, engine: str) -> Optional[str]:
    sql = "SHOW server_version" if engine == "postgresql" else "SELECT VERSION()"
    raw = getattr(connection, "connection", None)
    if raw is None:
        return None
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
    except Exception:
        return None
    finally:
        cursor.close()
    if not row:
        return None
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()), None)
    return str(value) if value else None


PLUGIN_CLASS = MaintenanceWindowPlugin
