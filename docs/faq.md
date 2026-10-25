# FAQ

## What is DB Storage Manager?

A PyQt6 desktop app for multi-engine database storage analysis, safe querying, encrypted connection management, and backups (local/S3/Google Drive).

## Which databases are supported?

Core: PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis.  
Optional extras: Oracle, SQL Server, ClickHouse, InfluxDB.

## Do I need cloud credentials to start?

No. Local SQLite works with zero external credentials.

## Where are passwords stored?

Encrypted with Fernet in `connections.enc` under the user data directory. The master key is `.master-key`.

## Is there a REST API or web UI?

Not in the current release. The product is a desktop application with a Python package API for programmatic access. A web interface is on the longer-term roadmap.

## Why did Oracle installs used to fail?

Older docs and extras pointed at obsolete `cx_Oracle`, which always needed Oracle Instant Client. The project now uses **`oracledb`** (python-oracledb) in **Thin mode** by default — `pip install -e ".[oracle]"` with no Instant Client for Oracle Database 12.1+. Instant Client is only required for Thick mode (11g, NNE, AC/TAC); set `ORACLE_CLIENT_LIB_DIR`. See [installation.md](installation.md).

## What do I need for SQL Server?

`pip install -e ".[mssql]"` (`pyodbc`) plus Microsoft ODBC Driver 18 on the host (unixODBC on Linux/macOS). Details: [installation.md](installation.md).

## Which Python versions are supported?

`python_requires>=3.10`. Validated on 3.10–3.12. Prefer 3.12 for local development if your system default is newer (for example 3.14).

## How do I report a security issue?

Email contact@voxhash.dev — see [SECURITY.md](../SECURITY.md).

## How do I run live connection probes against real databases?

Copy `tests/fixtures/connections.local.json.example` to `tests/fixtures/connections.local.json` (gitignored), fill real host/engine/database/user/password from your local projects, then:

```bash
pytest -v tests/test_real_connections.py
```

Unreachable ports and missing SQLite files are skipped. Probes call `test_connection()` only (Safe Mode / no writes). Optional: `DSM_E2E_CONNECTIONS_FILE` and `DSM_E2E_CONNECT_TIMEOUT` — see [configuration.md](configuration.md).

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md). Use Conventional Commits and the PR template under `.github/`.
