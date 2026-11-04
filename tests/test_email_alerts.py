"""Email alert channel over real SMTP (loopback sink, no mocks)."""

from __future__ import annotations

import base64
import socketserver
import threading
from email import message_from_bytes
from email.policy import default as default_policy
from typing import List

import pytest

from db_storage_manager.config import DEFAULT_EMAIL_ALERTS
from db_storage_manager.monitoring import (
    Alert,
    AlertSeverity,
    NotificationDispatcher,
)
from db_storage_manager.monitoring.notifications import (
    resolve_email_config,
    send_test_email,
    validate_email_config,
)
from db_storage_manager.security.auth import ROLE_PERMISSIONS, UserRole


class _Handler(socketserver.StreamRequestHandler):
    """Minimal but protocol-correct SMTP server (EHLO/AUTH PLAIN/MAIL/RCPT/DATA)."""

    def _send(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        server = self.server
        self._send("220 sink ESMTP")
        mail_from, rcpts = "", []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").strip()
            cmd = line.split(" ", 1)[0].upper()
            if cmd == "EHLO":
                self.wfile.write(
                    b"250-sink\r\n250-AUTH PLAIN\r\n250 8BITMIME\r\n"
                )
                self.wfile.flush()
            elif cmd == "AUTH":
                _, mech, blob = line.split(" ", 2)
                _, user, password = base64.b64decode(blob).split(b"\0")
                server.logins.append((user.decode(), password.decode()))
                if (user.decode(), password.decode()) == server.credentials:
                    self._send("235 ok")
                else:
                    self._send("535 bad credentials")
            elif cmd == "MAIL":
                mail_from = line.split(":", 1)[1].strip()
                rcpts = []
                self._send("250 ok")
            elif cmd == "RCPT":
                rcpts.append(line.split(":", 1)[1].strip())
                self._send("250 ok")
            elif cmd == "DATA":
                self._send("354 go")
                body = []
                while True:
                    part = self.rfile.readline()
                    if part in (b".\r\n", b""):
                        break
                    body.append(part)
                server.messages.append(
                    {
                        "from": mail_from,
                        "to": rcpts,
                        "raw": b"".join(body),
                    }
                )
                self._send("250 queued")
            elif cmd == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("250 ok")


class _SMTPSink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, credentials=("alerts", "s3cret-pass")):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.messages: List[dict] = []
        self.logins: List[tuple] = []
        self.credentials = credentials


@pytest.fixture
def smtp_sink():
    server = _SMTPSink()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _cfg(sink, **overrides):
    cfg = {
        **DEFAULT_EMAIL_ALERTS,
        "host": "127.0.0.1",
        "port": sink.server_address[1],
        "security": "none",
        "username": "alerts",
        "password": "s3cret-pass",
        "sender": "dsm@example.com",
        "recipients": ["oncall@example.com", "dba@example.com"],
        "min_severity": "critical",
        "cooldown_minutes": 30,
    }
    cfg.update(overrides)
    return cfg


def _body(message: dict):
    return message_from_bytes(message["raw"], policy=default_policy)


def test_validation_rules():
    base = {
        **DEFAULT_EMAIL_ALERTS,
        "host": "smtp.example.com",
        "sender": "a@example.com",
        "recipients": ["b@example.com"],
    }
    assert validate_email_config(base) == []
    assert validate_email_config({**base, "host": ""})
    assert validate_email_config({**base, "recipients": []})
    assert validate_email_config({**base, "sender": "nope"})
    assert validate_email_config({**base, "security": "none"})  # remote + plain
    assert validate_email_config({**base, "host": "localhost", "security": "none"}) == []
    assert validate_email_config({**base, "username": "u"})  # user without password
    assert validate_email_config({**base, "min_severity": "info"})
    assert validate_email_config({**base, "port": 0})


def test_send_test_email_delivers_real_message(smtp_sink):
    cfg = _cfg(smtp_sink)
    send_test_email(cfg)
    assert smtp_sink.logins == [("alerts", "s3cret-pass")]
    assert len(smtp_sink.messages) == 1
    msg = smtp_sink.messages[0]
    assert msg["to"] == ["<oncall@example.com>", "<dba@example.com>"]
    parsed = _body(msg)
    assert "Test message" in parsed["Subject"]
    assert parsed["From"] == "dsm@example.com"


def test_bad_credentials_fail_loudly(smtp_sink):
    import smtplib

    with pytest.raises(smtplib.SMTPAuthenticationError):
        send_test_email(_cfg(smtp_sink, password="wrong"))
    assert smtp_sink.messages == []


def test_dispatcher_emails_only_critical_alerts_and_respects_cooldown(smtp_sink):
    now = [1000.0]
    dispatcher = NotificationDispatcher(
        {"in_app": True, "desktop": False, "email": True}, clock=lambda: now[0]
    )
    dispatcher.set_email_config(_cfg(smtp_sink))

    warning = Alert("Slow queries", "p95 high", AlertSeverity.WARNING, "monitor")
    assert "email" not in dispatcher.notify(warning)

    critical = Alert("Disk full", "disk 97%", AlertSeverity.CRITICAL, "monitor")
    assert "email" in dispatcher.notify(critical)
    assert dispatcher.wait_email_idle()
    assert len(smtp_sink.messages) == 1
    parsed = _body(smtp_sink.messages[0])
    assert "Disk full" in parsed["Subject"] and "CRITICAL" in parsed["Subject"]
    assert "disk 97%" in parsed.get_content()

    # Same alert again inside the cooldown: not mailed again.
    assert "email" not in dispatcher.notify(
        Alert("Disk full", "disk 98%", AlertSeverity.CRITICAL, "monitor")
    )
    # A different alert is independent of that cooldown.
    assert "email" in dispatcher.notify(
        Alert("Connections", "limit hit", AlertSeverity.CRITICAL, "monitor")
    )
    dispatcher.wait_email_idle()
    assert len(smtp_sink.messages) == 2

    # After the cooldown the same alert is mailed again.
    now[0] += 31 * 60
    assert "email" in dispatcher.notify(
        Alert("Disk full", "disk 99%", AlertSeverity.CRITICAL, "monitor")
    )
    dispatcher.wait_email_idle()
    assert len(smtp_sink.messages) == 3


def test_failed_delivery_is_logged_and_retried(smtp_sink):
    dispatcher = NotificationDispatcher({"in_app": True, "desktop": False, "email": True})
    dispatcher.set_email_config(_cfg(smtp_sink, password="wrong"))
    alert = Alert("Replica lag", "lag 90s", AlertSeverity.CRITICAL, "monitor")
    dispatcher.notify(alert)
    dispatcher.wait_email_idle()
    assert any(e.get("title") == "Email alert failed" for e in dispatcher.in_app_log)
    failed = [d for d in dispatcher.delivered if d.get("channel") == "email"]
    assert failed and failed[0]["delivered"] is False and failed[0]["error"]

    # Fix the credentials: failure cleared the cooldown, so the next alert is sent.
    dispatcher.set_email_config(_cfg(smtp_sink))
    dispatcher.notify(Alert("Replica lag", "lag 95s", AlertSeverity.CRITICAL, "monitor"))
    dispatcher.wait_email_idle()
    assert len(smtp_sink.messages) == 1


def test_unconfigured_email_never_blocks_other_channels():
    dispatcher = NotificationDispatcher({"in_app": True, "desktop": False, "email": True})
    fired = dispatcher.notify(
        Alert("Disk full", "x", AlertSeverity.CRITICAL, "monitor")
    )
    assert fired == ["in_app"]
    assert any(
        "SMTP is not configured" in e.get("message", "") for e in dispatcher.in_app_log
    )


def test_environment_overrides_secure_store(monkeypatch, isolated_secure_store):
    store, _ = isolated_secure_store
    settings = store.get_settings()
    settings["email_alerts"] = {
        **DEFAULT_EMAIL_ALERTS,
        "host": "stored.example.com",
        "sender": "stored@example.com",
        "recipients": ["stored@example.com"],
    }
    store.set_settings(settings)
    assert resolve_email_config()["host"] == "stored.example.com"

    monkeypatch.setenv("DSM_SMTP_HOST", "env.example.com")
    monkeypatch.setenv("DSM_SMTP_PORT", "2525")
    monkeypatch.setenv("DSM_SMTP_TO", "a@example.com, b@example.com")
    cfg = resolve_email_config()
    assert cfg["host"] == "env.example.com"
    assert cfg["port"] == 2525
    assert cfg["recipients"] == ["a@example.com", "b@example.com"]


def test_monitor_role_can_watch_but_not_administer():
    perms = ROLE_PERMISSIONS[UserRole.MONITOR]
    assert {"monitoring:read", "monitoring:write", "connections:read"} <= set(perms)
    for forbidden in (
        "backups:restore",
        "backups:create",
        "connections:write",
        "settings:write",
        "users:manage",
        "plugins:manage",
    ):
        assert forbidden not in perms
