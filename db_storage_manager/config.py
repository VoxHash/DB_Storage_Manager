"""
Configuration management for DB Storage Manager
"""

import copy
import os
from pathlib import Path
from typing import Optional

# Application paths
APP_NAME = "DB Storage Manager"
APP_VERSION = "1.0.8"
# Same leaf on every OS. The display name is not a stable directory id;
# Linux already used this slug, and desktop-identity tests require it.
_DATA_DIR_NAME = "db-storage-manager"


def _user_data_dir() -> Path:
    """Per-user config directory.

    ``Path.home()`` runs only when the platform directory is missing.
    Using it as a ``getenv`` default evaluates it even when ``APPDATA``
    is set, and a Windows child with no ``USERPROFILE`` then crashes
    (there is no passwd fallback).
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = Path.home() / "AppData" / "Roaming"
        preferred = base / _DATA_DIR_NAME
        legacy = base / APP_NAME
        if not preferred.exists() and legacy.is_dir():
            try:
                legacy.rename(preferred)
            except OSError:
                return legacy
        return preferred
    return Path.home() / ".config" / _DATA_DIR_NAME


# User data directory
USER_DATA_DIR = _user_data_dir()

# Ensure user data directory exists
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Configuration file paths
CONNECTIONS_FILE = USER_DATA_DIR / "connections.enc"
SETTINGS_FILE = USER_DATA_DIR / "settings.enc"
SSH_KEYS_FILE = USER_DATA_DIR / "ssh-keys.enc"
USERS_FILE = USER_DATA_DIR / "users.enc"
SCHEDULED_BACKUPS_FILE = USER_DATA_DIR / "scheduled-backups.json"
# Fernet-encrypted map of schedule id -> DSMENC1 passphrase (never in the JSON schedule file)
SCHEDULED_BACKUP_SECRETS_FILE = USER_DATA_DIR / "scheduled-backup-secrets.enc"
BACKUP_DIR = USER_DATA_DIR / "backups"
# Append-only JSON-lines audit trail for destructive / security-relevant actions
AUDIT_LOG_FILE = USER_DATA_DIR / "audit.log"
PLUGINS_DIR = USER_DATA_DIR / "plugins"
# Fernet-encrypted map of plugin id -> LicenseChain license record (key never in plaintext)
PLUGIN_LICENSES_FILE = USER_DATA_DIR / "plugin-licenses.enc"
# Optional donations that keep the free core and built-in tools maintained
# (listed in .github/FUNDING.yml as github: voxhash)
SPONSORS_URL = "https://github.com/sponsors/VoxHash"
MASTER_KEY_FILE = USER_DATA_DIR / ".master-key"

# Ensure backup directory exists
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

# Default alert thresholds (mirrored in monitoring.alerts.DEFAULT_ALERT_THRESHOLDS)
DEFAULT_ALERT_THRESHOLDS = {
    "connection_count": {"warning": 50.0, "critical": 100.0},
    "query_time": {"warning": 1000.0, "critical": 5000.0},
    "cache_hit_ratio": {"warning": 80.0, "critical": 60.0},
    "disk_usage": {"warning": 75.0, "critical": 90.0},
}

DEFAULT_ALERT_CHANNELS = {
    "desktop": True,
    "in_app": True,
    # SMTP mail; off until Settings > Notifications has a working server
    "email": False,
    "webhook": False,
    "slack": False,
    "discord": False,
    "telegram": False,
}

# Dashboard customization (watched summary metrics + table columns)
DASHBOARD_METRIC_KEYS = ("total_size", "tables", "indexes")
DASHBOARD_COLUMN_KEYS = ("name", "size", "rows", "index_size", "bloat")

DEFAULT_DASHBOARD_LAYOUT = {
    "watched_metrics": list(DASHBOARD_METRIC_KEYS),
    "table_columns": list(DASHBOARD_COLUMN_KEYS),
    "metric_order": list(DASHBOARD_METRIC_KEYS),
    "last_connection_id": None,
    "active_layout": "Default",
    "saved_layouts": {
        "Default": {
            "watched_metrics": list(DASHBOARD_METRIC_KEYS),
            "table_columns": list(DASHBOARD_COLUMN_KEYS),
            "metric_order": list(DASHBOARD_METRIC_KEYS),
        }
    },
}

# Local plugin marketplace prefs (enable/disable map; registry lives under PLUGINS_DIR)
DEFAULT_PLUGINS_PREFS = {
    "enabled": {
        "migration": True,
        "data_comparison": True,
    }
}

# RBAC prefs (accounts themselves live in users.enc; this flag is informational)
DEFAULT_RBAC_PREFS = {
    "enabled": False,  # set True when users.enc has accounts (shared workstation)
}

# Companion pairing (SHA-256 of Bearer only — never store plaintext token or master key)
DEFAULT_COMPANION = {
    "pairing_token_hash": None,
    "pairing_created_at": None,
    "pairing_label": "",
    "revoked_at": None,
}

# Proton Drive cloud backup (credentials via env / SecureStore — never commit secrets)
DEFAULT_PROTON_DRIVE = {
    "remote": "protondrive",
    "path": "db-storage-manager-backups",
    "rclone_bin": "rclone",
    "prefer_encryption": True,
    # username / password / otp_secret_key stay unset here; load from
    # .env.protondrive.local or SecureStore settings["proton_drive"]
}

# Full restore is stable and on by default. Uncheck Settings → Backups to hide
# the Restore button. ``DSM_EXPERIMENTAL=1`` still forces it on.
DEFAULT_EXPERIMENTAL = {
    # Full Restore Backup (destructive: replaces objects in the target database)
    "restore": True,
}

# S3-compatible backup destination (AWS S3, MinIO, Cloudflare R2, Backblaze B2, ...).
# Secrets (access_key_id / secret_access_key) live in SecureStore or the AWS
# credential chain (env / profile / instance role) - never in this default.
DEFAULT_S3_BACKUP = {
    "bucket": "",
    "prefix": "db-storage-manager-backups/",
    "region": "us-east-1",
    "endpoint": "",
}

# SMTP alert channel for Monitoring. The password is stored encrypted in
# SecureStore (or read from DSM_SMTP_PASSWORD); nothing here is a secret.
DEFAULT_EMAIL_ALERTS = {
    "host": "",
    "port": 587,
    # "starttls" (587), "ssl" (465) or "none" (only for loopback / trusted relays)
    "security": "starttls",
    "username": "",
    "sender": "",
    "recipients": [],
    # Lowest severity that sends mail: "warning" or "critical"
    "min_severity": "critical",
    # Same alert title/source is mailed at most once per cooldown window
    "cooldown_minutes": 30,
}

# HTTPS webhook and Slack incoming webhook. The URL is a secret (a Slack URL
# contains the token) and lives in SecureStore. Same severity and cooldown
# rules as email. Nothing here is a secret.
DEFAULT_WEBHOOK_ALERTS = {
    "url": "",
    "min_severity": "critical",
    "cooldown_minutes": 30,
}
DEFAULT_SLACK_ALERTS = {
    "url": "",
    "min_severity": "critical",
    "cooldown_minutes": 30,
}
# Discord incoming webhook. The URL contains the token and lives in SecureStore.
# Off until the operator opts in on the Monitoring tab.
DEFAULT_DISCORD_ALERTS = {
    "url": "",
    "min_severity": "critical",
    "cooldown_minutes": 30,
}
# Telegram bot token and chat id. They live in SecureStore or
# DSM_TELEGRAM_BOT_TOKEN / DSM_TELEGRAM_CHAT_ID. Nothing here is a token.
# The app posts only to api.telegram.org.
DEFAULT_TELEGRAM_ALERTS = {
    "bot_token": "",
    "chat_id": "",
    "min_severity": "critical",
    "cooldown_minutes": 30,
}
# Per-connection SMTP. ``connections`` maps a saved connection id to a profile
# with the same fields as email alerts, plus ``enabled``. The password stays
# in SecureStore.
DEFAULT_CONNECTION_EMAIL_ALERTS = {"connections": {}}
# Extra health checks. Off until connection ids are saved and the plugin is
# installed. Credentials are the ones already stored for those connections.
DEFAULT_MULTI_CONNECTION_MONITOR = {
    "connection_ids": [],
    "min_interval_seconds": 60,
}

# Monitoring preferences (non-secret)
DEFAULT_MONITORING_PREFS = {
    # Connection id to start watching automatically when the app opens, so an
    # on-call / monitor user gets alerts without clicking Start.
    "autostart_connection_id": None,
}

# Cloud-managed databases (RDS / Cloud SQL / Azure SQL) — non-secret defaults only
DEFAULT_CLOUD_MANAGED = {
    "aws": {
        "region": "us-east-1",
        # access_key_id / secret_access_key / profile / ssl_ca_path via
        # .env.cloud.local or SecureStore cloud_managed.aws
    },
    "gcp": {
        # project_id / credentials_path via env or SecureStore
    },
    "azure": {
        # subscription_id / tenant_id / client_id via env or SecureStore;
        # client_secret via env only preferred
    },
}

# Default settings
DEFAULT_SETTINGS = {
    "theme": "dark",  # light, dark, dracula
    "language": "en",
    "safe_mode": True,
    "auto_connect": False,
    "notifications": True,
    # Desktop notification auto-dismiss (seconds, clamped 2-60 by the tray)
    "notification_timeout_seconds": 5,
    # Manual update checks: "stable" or "experimental" (GitHub pre-releases).
    # Automatic checks are off until Settings → Updates opts in.
    "update_channel": "stable",
    "update_auto_check": False,
    # Backup retention. Off until enabled. connections maps id -> override.
    "retention": {
        "enabled": False,
        "keep_daily": 7,
        "keep_monthly": 6,
        "connections": {},
    },
    "telemetry": False,
    # Empty keeps BACKUP_DIR. A non-empty value is an absolute directory
    # chosen in Settings → Backups & Adapters.
    "local_backup_dir": "",
    "alert_thresholds": copy.deepcopy(DEFAULT_ALERT_THRESHOLDS),
    "alert_channels": copy.deepcopy(DEFAULT_ALERT_CHANNELS),
    "dashboard_layout": copy.deepcopy(DEFAULT_DASHBOARD_LAYOUT),
    "plugins": copy.deepcopy(DEFAULT_PLUGINS_PREFS),
    "rbac": copy.deepcopy(DEFAULT_RBAC_PREFS),
    "companion": copy.deepcopy(DEFAULT_COMPANION),
    "proton_drive": copy.deepcopy(DEFAULT_PROTON_DRIVE),
    "cloud_managed": copy.deepcopy(DEFAULT_CLOUD_MANAGED),
    "experimental": copy.deepcopy(DEFAULT_EXPERIMENTAL),
    "s3_backup": copy.deepcopy(DEFAULT_S3_BACKUP),
    "email_alerts": copy.deepcopy(DEFAULT_EMAIL_ALERTS),
    "webhook_alerts": copy.deepcopy(DEFAULT_WEBHOOK_ALERTS),
    "slack_alerts": copy.deepcopy(DEFAULT_SLACK_ALERTS),
    "discord_alerts": copy.deepcopy(DEFAULT_DISCORD_ALERTS),
    "telegram_alerts": copy.deepcopy(DEFAULT_TELEGRAM_ALERTS),
    "connection_email_alerts": copy.deepcopy(DEFAULT_CONNECTION_EMAIL_ALERTS),
    "multi_connection_monitor": copy.deepcopy(DEFAULT_MULTI_CONNECTION_MONITOR),
    "monitoring": copy.deepcopy(DEFAULT_MONITORING_PREFS),
}

# Database connection defaults
DEFAULT_TIMEOUT = 30
DEFAULT_PORT = {
    "postgresql": 5432,
    "mysql": 3306,
    "sqlite": None,
    "mongodb": 27017,
    "redis": 6379,
    "oracle": 1521,
    "sqlserver": 1433,
    "mssql": 1433,
    "clickhouse": 9000,
    "influxdb": 8086,
}
