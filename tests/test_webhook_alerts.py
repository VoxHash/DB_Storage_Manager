"""Webhook and Slack use the same severity and cooldown rules as email."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from db_storage_manager.monitoring.alerts import Alert, AlertSeverity
from db_storage_manager.monitoring.notifications import (
    NotificationDispatcher,
    build_slack_payload,
    validate_alert_url,
    validate_webhook_config,
)


def test_url_rules_block_metadata_and_limit_slack():
    assert validate_alert_url("http://169.254.169.254/latest")
    assert validate_alert_url("https://hooks.slack.com/services/T/B/x", slack=True) == []
    assert validate_alert_url("https://example.com/hook", slack=True)
    assert validate_alert_url("http://127.0.0.1:9/hook") == []
    assert validate_alert_url("http://alerts.example/hook")
    assert validate_webhook_config(
        {"url": "https://example.com/hook", "min_severity": "critical"}
    ) == []


def test_webhook_posts_json_and_respects_cooldown():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            received.append(json.loads(self.rfile.read(length).decode()))
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    try:
        now = [0.0]
        dispatcher = NotificationDispatcher(
            {"in_app": False, "desktop": False, "email": False, "webhook": True},
            clock=lambda: now[0],
        )
        dispatcher.set_webhook_config(
            {"url": url, "min_severity": "warning", "cooldown_minutes": 30}
        )
        alert = Alert("Disk", "90 percent", AlertSeverity.WARNING, "storage")
        assert dispatcher.notify(alert) == ["webhook"]
        info = Alert("Note", "fine", AlertSeverity.INFO, "storage")
        assert "webhook" not in dispatcher.notify(info)
        assert dispatcher.notify(alert) == []
        now[0] = 31 * 60
        assert dispatcher.notify(alert) == ["webhook"]
        assert dispatcher.wait_email_idle(5)
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert len(received) == 2
    assert received[0]["title"] == "Disk"
    assert received[0]["severity"] == "warning"
    assert url not in json.dumps(received)
    assert all("http" not in entry.get("message", "") for entry in dispatcher.in_app_log)


def test_slack_body_is_the_incoming_webhook_text():
    seen = []

    def sender(url, payload):
        seen.append((url, payload))

    dispatcher = NotificationDispatcher(
        {"in_app": False, "desktop": False, "email": False, "slack": True},
        slack_sender=sender,
    )
    dispatcher.set_slack_config(
        {
            "url": "https://hooks.slack.com/services/T0/B0/secret",
            "min_severity": "critical",
            "cooldown_minutes": 0,
        }
    )
    alert = Alert("Down", "unhealthy", AlertSeverity.CRITICAL, "health_monitor")
    assert dispatcher.notify(alert) == ["slack"]
    assert dispatcher.wait_email_idle(2)
    assert seen[0][1] == build_slack_payload(alert)
    assert "secret" not in json.dumps(dispatcher.delivered)
    warning = Alert("Warm", "slow", AlertSeverity.WARNING, "health_monitor")
    assert dispatcher.notify(warning) == []
