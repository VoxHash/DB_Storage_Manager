"""
Notification channels for monitoring alerts.

Channels fire when AlertManager emits a new alert. Desktop delivery uses a
caller-provided handler (typically QSystemTrayIcon.showMessage); in-app
delivery appends to a durable in-memory log the Monitoring UI can display;
email delivery speaks real SMTP (STARTTLS / implicit TLS) from a worker thread
so a slow mail server never blocks the GUI or the monitoring poll.
"""

from __future__ import annotations

import os
import smtplib
import socket
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .alerts import Alert

DEFAULT_ALERT_CHANNELS: Dict[str, bool] = {
    "desktop": True,
    "in_app": True,
    "email": False,
}

DesktopHandler = Callable[[str, str, str], None]

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
EMAIL_SECURITY_MODES = ("starttls", "ssl", "none")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


# --------------------------------------------------------------------------
# Email (SMTP)
# --------------------------------------------------------------------------


def resolve_email_config(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SecureStore ``email_alerts`` merged with ``DSM_SMTP_*`` environment values."""
    from ..config import DEFAULT_EMAIL_ALERTS

    if settings is None:
        from ..security.store import SecureStore

        settings = SecureStore().get_settings()
    cfg: Dict[str, Any] = dict(DEFAULT_EMAIL_ALERTS)
    cfg.update(settings.get("email_alerts") or {})

    env = os.environ
    for env_name, key in (
        ("DSM_SMTP_HOST", "host"),
        ("DSM_SMTP_USERNAME", "username"),
        ("DSM_SMTP_PASSWORD", "password"),
        ("DSM_SMTP_FROM", "sender"),
        ("DSM_SMTP_SECURITY", "security"),
    ):
        value = env.get(env_name, "").strip()
        if value:
            cfg[key] = value
    port = env.get("DSM_SMTP_PORT", "").strip()
    if port.isdigit():
        cfg["port"] = int(port)
    to = env.get("DSM_SMTP_TO", "").strip()
    if to:
        cfg["recipients"] = [r.strip() for r in to.split(",") if r.strip()]

    recipients = cfg.get("recipients") or []
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.replace(";", ",").split(",")]
    cfg["recipients"] = [r for r in recipients if r]
    cfg["security"] = str(cfg.get("security") or "starttls").lower()
    cfg["min_severity"] = str(cfg.get("min_severity") or "critical").lower()
    try:
        cfg["port"] = int(cfg.get("port") or 0)
    except (TypeError, ValueError):
        cfg["port"] = 0
    try:
        cfg["cooldown_minutes"] = max(0, int(cfg.get("cooldown_minutes") or 0))
    except (TypeError, ValueError):
        cfg["cooldown_minutes"] = 30
    return cfg


def validate_email_config(cfg: Dict[str, Any]) -> List[str]:
    """Human-readable problems (empty list = ready to send)."""
    errors: List[str] = []
    host = str(cfg.get("host") or "").strip()
    if not host:
        errors.append("SMTP host is required")
    port = cfg.get("port") or 0
    if not isinstance(port, int) or not (1 <= port <= 65535):
        errors.append("SMTP port must be between 1 and 65535")
    security = cfg.get("security")
    if security not in EMAIL_SECURITY_MODES:
        errors.append("Security must be starttls, ssl or none")
    elif security == "none" and host.lower() not in _LOOPBACK_HOSTS:
        errors.append(
            "Unencrypted SMTP is only allowed for localhost; use STARTTLS or SSL"
        )
    if not str(cfg.get("sender") or "").strip() or "@" not in str(cfg.get("sender")):
        errors.append("A sender address is required")
    recipients = cfg.get("recipients") or []
    if not recipients or any("@" not in r for r in recipients):
        errors.append("At least one valid recipient is required")
    if cfg.get("min_severity") not in ("warning", "critical"):
        errors.append("Minimum severity must be warning or critical")
    if bool(cfg.get("username")) != bool(cfg.get("password")):
        errors.append("SMTP username and password must be set together")
    return errors


def build_alert_message(
    cfg: Dict[str, Any], title: str, message: str, severity: str, source: str,
    timestamp: Optional[str] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[DB Storage Manager][{severity.upper()}] {title}"
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(cfg["recipients"])
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="db-storage-manager.local")
    msg.set_content(
        "\n".join(
            [
                f"Severity : {severity}",
                f"Alert    : {title}",
                f"Source   : {source}",
                f"Host     : {socket.gethostname()}",
                f"Time     : {timestamp or datetime.now().isoformat()}",
                "",
                message,
                "",
                "-- DB Storage Manager monitoring",
            ]
        )
    )
    return msg


def send_email(
    cfg: Dict[str, Any],
    msg: EmailMessage,
    *,
    timeout: float = 15.0,
    context: Optional[ssl.SSLContext] = None,
) -> None:
    """Deliver ``msg`` over real SMTP. Raises on any failure.

    Pass ``context`` when calling from a worker. On macOS,
    ``ssl.create_default_context()`` loads the system trust store and
    waits for the main CFRunLoop. Doing that on a worker while the
    main thread is blocked in ``Thread.join`` never returns.
    """
    errors = validate_email_config(cfg)
    if errors:
        raise ValueError("; ".join(errors))
    host, port, security = cfg["host"], int(cfg["port"]), cfg["security"]
    if security in ("ssl", "starttls") and context is None:
        context = ssl.create_default_context()
    if security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            host, port, timeout=timeout, context=context
        )
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    with client:
        client.ehlo()
        if security == "starttls":
            client.starttls(context=context)
            client.ehlo()
        if cfg.get("username"):
            client.login(cfg["username"], cfg["password"])
        client.send_message(msg, from_addr=cfg["sender"], to_addrs=cfg["recipients"])


def send_test_email(cfg: Dict[str, Any], *, timeout: float = 15.0) -> None:
    """Send a clearly-labelled test message with the same code path as alerts."""
    send_email(
        cfg,
        build_alert_message(
            cfg,
            "Test message",
            "This is a test of the DB Storage Manager email alert channel.",
            "info",
            "settings",
        ),
        timeout=timeout,
    )


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------


class NotificationDispatcher:
    """Route alerts to enabled notification channels."""

    def __init__(
        self,
        channels: Optional[Dict[str, bool]] = None,
        *,
        email_sender: Optional[Callable[[Dict[str, Any], EmailMessage], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.channels: Dict[str, bool] = dict(DEFAULT_ALERT_CHANNELS)
        if channels:
            self.configure(channels)
        self.in_app_log: List[Dict[str, Any]] = []
        self.delivered: List[Dict[str, Any]] = []
        self._desktop_handler: Optional[DesktopHandler] = None
        self._email_config: Dict[str, Any] = {}
        self._email_sender = email_sender or send_email
        self._clock = clock
        self._email_last_sent: Dict[Tuple[str, str], float] = {}
        self._email_threads: List[threading.Thread] = []
        self._email_lock = threading.Lock()

    def configure(self, channels: Dict[str, bool]) -> None:
        """Update which channels are enabled (unknown keys ignored)."""
        for key in DEFAULT_ALERT_CHANNELS:
            if key in channels:
                self.channels[key] = bool(channels[key])

    def set_desktop_handler(self, handler: Optional[DesktopHandler]) -> None:
        """Register OS/desktop notification delivery (title, message, severity)."""
        self._desktop_handler = handler

    def set_email_config(self, cfg: Optional[Dict[str, Any]]) -> None:
        """Set SMTP parameters (see :func:`resolve_email_config`)."""
        self._email_config = dict(cfg or {})

    def get_channels(self) -> Dict[str, bool]:
        return dict(self.channels)

    def clear_in_app_log(self) -> None:
        self.in_app_log.clear()

    def wait_email_idle(self, timeout: float = 10.0) -> bool:
        """Block until queued email deliveries finished (tests / shutdown)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._email_lock:
                self._email_threads = [t for t in self._email_threads if t.is_alive()]
                pending = list(self._email_threads)
            if not pending:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            pending[0].join(remaining)

    def _email_due(self, alert: Alert) -> Optional[str]:
        """Return a reason string when this alert must NOT be mailed, else None."""
        cfg = self._email_config
        if validate_email_config(cfg):
            return "email_not_configured"
        if SEVERITY_RANK.get(alert.severity.value, 0) < SEVERITY_RANK.get(
            cfg["min_severity"], 2
        ):
            return "below_min_severity"
        cooldown = int(cfg.get("cooldown_minutes") or 0) * 60
        key = (alert.source, alert.title)
        now = self._clock()
        with self._email_lock:
            last = self._email_last_sent.get(key)
            if cooldown and last is not None and now - last < cooldown:
                return "cooldown"
            self._email_last_sent[key] = now
        return None

    def _queue_email(self, alert: Alert, record_base: Dict[str, Any]) -> bool:
        entry = {**record_base, "channel": "email", "delivered": False}
        skip = self._email_due(alert)
        if skip is not None:
            if skip == "email_not_configured":
                entry["error"] = skip
                self.delivered.append(entry)
                self.in_app_log.append({**entry, "message": "Email alert skipped: SMTP is not configured"})
            else:
                entry["skipped"] = skip
                self.delivered.append(entry)
            return False

        cfg = dict(self._email_config)
        msg = build_alert_message(
            cfg,
            alert.title,
            alert.message,
            alert.severity.value,
            alert.source,
            alert.timestamp,
        )
        self.delivered.append(entry)
        # Trust store on this thread, before the worker. See send_email.
        security = str(cfg.get("security") or "")
        if security in ("ssl", "starttls"):
            context: Optional[ssl.SSLContext] = ssl.create_default_context()
        else:
            context = None
        sender = self._email_sender

        def worker() -> None:
            try:
                if sender is send_email:
                    send_email(cfg, msg, context=context)
                else:
                    sender(cfg, msg)
                entry["delivered"] = True
            except Exception as exc:  # noqa: BLE001 - surfaced in the log
                entry["error"] = f"{type(exc).__name__}: {exc}"
                # Let a failed delivery be retried by the next alert.
                with self._email_lock:
                    self._email_last_sent.pop((alert.source, alert.title), None)
                self.in_app_log.append(
                    {
                        **record_base,
                        "channel": "email",
                        "severity": "warning",
                        "title": "Email alert failed",
                        "message": f"{alert.title}: {entry['error']}",
                    }
                )

        thread = threading.Thread(target=worker, name="dsm-alert-email", daemon=True)
        with self._email_lock:
            self._email_threads.append(thread)
        thread.start()
        return True

    def notify(self, alert: Alert) -> List[str]:
        """Deliver alert on every enabled channel. Returns channel names that fired."""
        fired: List[str] = []
        severity = alert.severity.value
        record_base = {
            "alert_id": alert.id,
            "title": alert.title,
            "message": alert.message,
            "severity": severity,
            "source": alert.source,
            "timestamp": datetime.now().isoformat(),
        }

        if self.channels.get("in_app", True):
            entry = {**record_base, "channel": "in_app"}
            self.in_app_log.append(entry)
            self.delivered.append(entry)
            fired.append("in_app")

        if self.channels.get("desktop", True):
            entry = {**record_base, "channel": "desktop"}
            if self._desktop_handler is not None:
                try:
                    self._desktop_handler(alert.title, alert.message, severity)
                    entry["delivered"] = True
                except Exception as exc:
                    entry["delivered"] = False
                    entry["error"] = str(exc)
            else:
                # No OS handler yet — still record the attempt so tests/UI can assert.
                entry["delivered"] = False
                entry["error"] = "no_desktop_handler"
            self.delivered.append(entry)
            fired.append("desktop")

        if self.channels.get("email", False):
            if self._queue_email(alert, record_base):
                fired.append("email")

        return fired
