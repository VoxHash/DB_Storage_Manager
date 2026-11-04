"""Per-connection SMTP alerts.

The workstation-wide profile on Settings → Notifications is unchanged. This
channel is opt-in per saved connection. The password stays in SecureStore and
is not copied into the plugin directory, the return value, or the audit log.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from ..security.auth import PermissionDenied, get_auth_manager
from .alerts import Alert
from .notifications import (
    SEVERITY_RANK,
    build_alert_message,
    send_email,
    validate_email_config,
)

PLUGIN_ID = "connection-email-alerts"
SETTINGS_KEY = "connection_email_alerts"

_last_sent: Dict[tuple, float] = {}


def reset_state() -> None:
    """Clear the in-process cooldown (tests)."""
    _last_sent.clear()


def _settings() -> Dict[str, Any]:
    from ..security.store import SecureStore

    settings = SecureStore().get_settings()
    blob = settings.get(SETTINGS_KEY)
    if not isinstance(blob, dict):
        blob = {"connections": {}}
    connections = blob.get("connections")
    if not isinstance(connections, dict):
        blob = {**blob, "connections": {}}
    return blob


def _save(blob: Dict[str, Any]) -> None:
    from ..security.store import SecureStore

    store = SecureStore()
    settings = store.get_settings()
    settings[SETTINGS_KEY] = blob
    store.set_settings(settings)


def _public_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Profile without the password."""
    return {
        "enabled": bool(profile.get("enabled")),
        "host": profile.get("host") or "",
        "port": profile.get("port"),
        "security": profile.get("security"),
        "username": profile.get("username") or "",
        "sender": profile.get("sender") or "",
        "recipients": list(profile.get("recipients") or []),
        "min_severity": profile.get("min_severity") or "critical",
        "cooldown_minutes": profile.get("cooldown_minutes"),
    }


def save_profile(connection_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Store one connection's SMTP profile. Requires ``settings:write``."""
    get_auth_manager().require("settings:write")
    connection_id = str(connection_id or "").strip()
    if not connection_id:
        return {
            "status": "not_available",
            "reason": "A connection id is required.",
        }
    blob = _settings()
    current = dict(blob["connections"].get(connection_id) or {})
    merged = dict(current)
    for key in (
        "enabled",
        "host",
        "port",
        "security",
        "username",
        "sender",
        "recipients",
        "min_severity",
        "cooldown_minutes",
    ):
        if key in profile:
            merged[key] = profile[key]
    password = profile.get("password")
    if isinstance(password, str) and password:
        merged["password"] = password
    elif "password" in profile and not password and not merged.get("username"):
        merged.pop("password", None)
    merged["enabled"] = bool(merged.get("enabled"))
    blob["connections"][connection_id] = merged
    _save(blob)
    return {
        "status": "saved",
        "connection_id": connection_id,
        "profile": _public_profile(merged),
    }


def _profile(connection_id: str) -> Optional[Dict[str, Any]]:
    raw = _settings()["connections"].get(connection_id)
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    return raw


def plan_send(
    alert: Alert,
    *,
    clock: Callable[[], float] = time.monotonic,
    require_installed: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return a send plan, or None when this alert must not be mailed.

    The plan holds the SMTP password in memory for the worker thread. Callers
    must not log it. ``require_installed`` is for the core dispatcher, which
    must not send unless the operator installed this plugin.
    """
    connection_id = getattr(alert, "connection_id", None)
    if not connection_id:
        return None
    if require_installed and not _installed():
        return None
    try:
        get_auth_manager().require("monitoring:read")
    except PermissionDenied:
        return None
    profile = _profile(str(connection_id))
    if profile is None:
        return None
    if validate_email_config(profile):
        return None
    if SEVERITY_RANK.get(alert.severity.value, 0) < SEVERITY_RANK.get(
        str(profile.get("min_severity") or "critical"), 2
    ):
        return None
    cooldown = int(profile.get("cooldown_minutes") or 0) * 60
    key = (str(connection_id), alert.source, alert.title)
    now = clock()
    last = _last_sent.get(key)
    if cooldown and last is not None and now - last < cooldown:
        return None
    _last_sent[key] = now
    return {
        "key": key,
        "profile": dict(profile),
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity.value,
        "source": alert.source,
        "timestamp": alert.timestamp,
    }


def send_plan(
    plan: Dict[str, Any],
    *,
    sender: Optional[Callable[..., None]] = None,
) -> None:
    """Send one planned message. Clears the cooldown when delivery fails."""
    if sender is None:
        sender = send_email
    profile = plan["profile"]
    message = build_alert_message(
        profile,
        plan["title"],
        plan["message"],
        plan["severity"],
        plan["source"],
        plan.get("timestamp"),
    )
    try:
        sender(profile, message)
    except Exception:
        _last_sent.pop(plan["key"], None)
        raise


def _installed() -> bool:
    from pathlib import Path

    from ..plugins.loader import load_plugin_from_directory
    from ..plugins.marketplace import LocalPluginMarketplace

    market = LocalPluginMarketplace()
    for row in market.list_installed():
        if row.get("id") != PLUGIN_ID or row.get("source") == "builtin":
            continue
        if not market.is_enabled(PLUGIN_ID):
            return False
        path = row.get("path")
        if path and Path(path).is_dir():
            # Touch the install so a broken copy is not treated as ready.
            load_plugin_from_directory(Path(path))
            return True
    return False


def deliver(alert: Alert, *, sender: Callable[..., None] = send_email) -> Dict[str, Any]:
    """Send when the plugin is installed and this connection opted in."""
    plan = plan_send(alert, require_installed=True)
    if plan is None:
        return {"status": "not_available", "reason": "No opt-in SMTP profile for this alert."}
    try:
        send_plan(plan, sender=sender)
    except Exception as exc:  # noqa: BLE001 - type only; the message can contain the host
        return {"status": "fail", "reason": type(exc).__name__}
    return {"status": "sent", "connection_id": plan["key"][0]}


def handle(
    connection_id: Optional[str] = None,
    alert: Optional[Alert] = None,
    *,
    profile: Optional[Dict[str, Any]] = None,
    sender: Callable[..., None] = send_email,
    clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Plugin entry. Saving a profile needs ``settings:write``. Sending needs ``monitoring:read``."""
    if profile is not None:
        saved = save_profile(str(connection_id or ""), profile)
        if alert is None or saved.get("status") != "saved":
            return saved
    if alert is None:
        return {
            "status": "not_available",
            "reason": "No alert was given, and no profile was saved.",
        }
    if connection_id and not getattr(alert, "connection_id", None):
        alert.connection_id = str(connection_id)
    get_auth_manager().require("monitoring:read")
    plan = plan_send(alert, clock=clock)
    if plan is None:
        reason = "This connection has no opt-in SMTP profile."
        profile_row = _profile(str(getattr(alert, "connection_id", "") or ""))
        if profile_row is not None and validate_email_config(profile_row):
            reason = "The SMTP profile for this connection is incomplete."
        elif profile_row is not None:
            reason = "This alert is below the minimum severity or still in cooldown."
        return {"status": "not_available", "reason": reason}
    try:
        send_plan(plan, sender=sender)
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "reason": type(exc).__name__}
    return {"status": "sent", "connection_id": plan["key"][0]}
