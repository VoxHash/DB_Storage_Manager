"""
Configuration management for DB Storage Manager
"""

import copy
import os
from pathlib import Path
from typing import Optional

# Application paths
APP_NAME = "DB Storage Manager"
APP_VERSION = "1.0.5"

# User data directory
if os.name == "nt":  # Windows
    USER_DATA_DIR = (
        Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    )
else:  # macOS/Linux
    USER_DATA_DIR = Path.home() / ".config" / APP_NAME.lower().replace(" ", "-")

# Ensure user data directory exists
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Configuration file paths
CONNECTIONS_FILE = USER_DATA_DIR / "connections.enc"
SETTINGS_FILE = USER_DATA_DIR / "settings.enc"
SSH_KEYS_FILE = USER_DATA_DIR / "ssh-keys.enc"
USERS_FILE = USER_DATA_DIR / "users.enc"
SCHEDULED_BACKUPS_FILE = USER_DATA_DIR / "scheduled-backups.json"
BACKUP_DIR = USER_DATA_DIR / "backups"
PLUGINS_DIR = USER_DATA_DIR / "plugins"
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

# Default settings
DEFAULT_SETTINGS = {
    "theme": "dark",  # light, dark, dracula
    "language": "en",
    "safe_mode": True,
    "auto_connect": False,
    "notifications": True,
    "telemetry": False,
    "alert_thresholds": copy.deepcopy(DEFAULT_ALERT_THRESHOLDS),
    "alert_channels": copy.deepcopy(DEFAULT_ALERT_CHANNELS),
    "dashboard_layout": copy.deepcopy(DEFAULT_DASHBOARD_LAYOUT),
    "plugins": copy.deepcopy(DEFAULT_PLUGINS_PREFS),
    "rbac": copy.deepcopy(DEFAULT_RBAC_PREFS),
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
