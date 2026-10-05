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

## Why does Oracle install fail?

`cx_Oracle` needs Oracle Instant Client and often fails in pure pip environments. Install Instant Client, then `pip install -e ".[oracle]"`, or skip Oracle until needed.

## Which Python versions are supported?

`python_requires>=3.10`. Validated on 3.10–3.12. Prefer 3.12 for local development if your system default is newer (for example 3.14).

## How do I report a security issue?

Email contact@voxhash.dev — see [SECURITY.md](../SECURITY.md).

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md). Use Conventional Commits and the PR template under `.github/`.
