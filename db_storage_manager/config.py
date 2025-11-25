"""
Configuration management for DB Storage Manager
"""

import os
from pathlib import Path
from typing import Optional

# Application paths
APP_NAME = "DB Storage Manager"
APP_VERSION = "1.0.0"

# User data directory
if os.name == "nt":  # Windows
    USER_DATA_DIR = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
else:  # macOS/Linux
    USER_DATA_DIR = Path.home() / ".config" / APP_NAME.lower().replace(" ", "-")

# Ensure user data directory exists
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Configuration file paths
CONNECTIONS_FILE = USER_DATA_DIR / "connections.enc"
SETTINGS_FILE = USER_DATA_DIR / "settings.enc"
SSH_KEYS_FILE = USER_DATA_DIR / "ssh-keys.enc"
SCHEDULED_BACKUPS_FILE = USER_DATA_DIR / "scheduled-backups.json"
BACKUP_DIR = USER_DATA_DIR / "backups"
MASTER_KEY_FILE = USER_DATA_DIR / ".master-key"

# Ensure backup directory exists
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Default settings
DEFAULT_SETTINGS = {
    "theme": "dark",  # light, dark, dracula
    "language": "en",
    "safe_mode": True,
    "auto_connect": False,
    "notifications": True,
    "telemetry": False,
}

# Database connection defaults
DEFAULT_TIMEOUT = 30
DEFAULT_PORT = {
    "postgresql": 5432,
    "mysql": 3306,
    "sqlite": None,
    "mongodb": 27017,
    "redis": 6379,
}

