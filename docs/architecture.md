# Architecture

DB Storage Manager is a cross-platform desktop application built with Python and PyQt6. It uses a modular layout: GUI, async database drivers, encrypted local storage, and pluggable backup adapters.

## Components

### Desktop UI (PyQt6)

- `gui/main_window.py` — tabbed main window
- Feature widgets: dashboard, connections, query, backups, settings, monitoring, charts
- Background work uses Qt threading patterns so the UI stays responsive while async DB calls run

### Database layer

- `db/base.py` — `ConnectionConfig`, result TypedDicts, `DatabaseConnection` ABC
- `db/factory.py` — `DatabaseConnectionFactory.create_connection(config)`
- Drivers: PostgreSQL, MySQL, SQLite, MongoDB, Redis, Oracle, SQL Server, ClickHouse, InfluxDB
- Optional engines import their drivers lazily and raise `ImportError` with install hints when missing

### Security

- `security/store.py` — Fernet encryption for connections, settings, and SSH keys
- Per-install master key at `.master-key`
- Safe mode blocks non-SELECT queries in SQL-like drivers
- Local-only credential storage (cloud SDKs only used when backup/cloud features are invoked)

### Backups

- Adapter pattern: Local, S3, Google Drive
- Scheduler for recurring jobs
- Compression and optional encryption supported by adapters/manager

### Cross-cutting

- `themes/` — light/dark/dracula-style themes
- `i18n/` — language manager
- `ssh/` — Paramiko tunnels
- `monitoring/`, `analysis/`, `cloud/`, `data/`, `plugins/` — advanced features shipped in-tree

## Data flow

```
User Input → Connection Dialog → Validation → Fernet Encrypt → connections.enc
Connection → Factory → Driver → async query/analyze → UI update
Query → Safe Mode check → execute_query → QueryResult
Backup → export → compress/encrypt → adapter → storage
```

## Technology stack

- Python 3.10+, PyQt6 / PyQt6-Charts
- Drivers: psycopg2-binary, pymysql, aiosqlite, pymongo, redis; optional cx_Oracle, pyodbc, clickhouse-driver, influxdb-client
- cryptography (Fernet), paramiko, boto3, Google API client, schedule, pandas/numpy/matplotlib

## Packaging and CI

- `setup.py` provides the `db-storage-manager` console script
- `.github/workflows/ci.yml` — lint/test/build across Ubuntu, Windows, macOS and Python 3.10–3.12
- `.github/workflows/release.yml` — tagged `v*` builds for executable artifacts

## Security notes (folded from prior security docs)

- Fernet AES-128-CBC + HMAC-SHA256 for stored secrets
- Restrictive file permissions on the master key (Unix `600`)
- Telemetry off by default
- Report vulnerabilities to contact@voxhash.dev (see root [SECURITY.md](../SECURITY.md))
