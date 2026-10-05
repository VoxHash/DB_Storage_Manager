# Getting Started

## Prerequisites

- Python **3.10, 3.11, or 3.12** (recommended). System Python 3.14 may work for core installs after optional drivers are excluded, but CI targets 3.10–3.12.
- `pip` and a virtual environment
- Display / desktop session for the PyQt6 GUI (or `QT_QPA_PLATFORM=offscreen` for smoke tests)
- For Linux GUI packages, system Qt libraries may help: `sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtcharts`

No API keys or cloud credentials are required for local SQLite usage. AWS, Google Drive, Azure, LDAP, and Oracle Instant Client are only needed when those features are used.

## Install and launch

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
python -m db_storage_manager.main
# or: db-storage-manager
```

Optional engines (install only what you need):

```bash
pip install -e ".[mssql,clickhouse,influxdb]"
# Oracle requires Instant Client and often fails on pure-pip builds:
pip install -e ".[oracle]"
```

## First steps

### 1. Add a connection

1. Open the **Connections** tab
2. Click **Add Connection**
3. Choose a database type and enter host/port/database/user/password (or a SQLite file path)
4. Click **Test Connection**, then save

Credentials are encrypted with Fernet and stored under the user data directory (see [configuration.md](configuration.md)).

### 2. Analyze storage

1. Open the **Dashboard** tab
2. Select a saved connection
3. Click **Analyze**
4. Review total size, tables, indexes, and largest objects

### 3. Run queries

1. Open the **Query Console** tab
2. Select a connection
3. Keep **Safe Mode** enabled for production databases (blocks non-SELECT statements)
4. Execute and inspect results / explain plans when available

### 4. Backups

1. Open the **Backups** tab
2. Choose Local, S3, or Google Drive adapter
3. Configure compression/encryption as needed
4. Create a backup or schedule recurring jobs

## Where data lives

On Linux/macOS: `~/.config/db-storage-manager/`  
On Windows: `%APPDATA%\DB Storage Manager\`

Files include encrypted connections, settings, SSH keys, scheduled backups, and local backup payloads. The master encryption key is stored as `.master-key` with mode `600` on Unix.

## Next reading

- [Quick Start](quick-start.md)
- [Usage](usage.md)
- [Troubleshooting](troubleshooting.md)
- [Example 01](examples/example-01.md)
