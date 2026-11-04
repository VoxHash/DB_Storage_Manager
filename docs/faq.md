# FAQ

## What is DB Storage Manager?

A PyQt6 desktop app for multi-engine database storage analysis, safe querying, encrypted connection management, and backups (local/S3/Google Drive).

## Which databases are supported?

Core: PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis.  
Optional extras: Oracle, SQL Server, ClickHouse, InfluxDB.

## Do I need cloud credentials to start?

No. Local SQLite works with zero external credentials. AWS RDS / GCP Cloud SQL / Azure SQL discovery and IAM/Entra connect helpers are optional — configure `.env.cloud.local` (see `.env.cloud.local.example`) only when using **Discover Cloud…**.

## How do I connect to RDS / Cloud SQL / Azure SQL?

Use **Connections → Discover Cloud…** after setting provider credentials, or add a profile manually with the managed endpoint. Prefer IAM (RDS) or Entra access tokens (Azure SQL) via `extra.auth_mode`; Cloud SQL IAM DB auth needs the Auth Proxy or `cloud-sql-python-connector` (`pip install -e ".[gcp]"`). See [configuration.md](configuration.md).

## Where are passwords stored?

Encrypted with Fernet in `connections.enc` under the user data directory. The master key is `.master-key`.

## Why does the dock group DSM with Telegram (or closing one affects the other)?

Both are Python/Qt GUIs. Without a unique FreeDesktop id, Wayland/KDE treats them as generic `python3` and stacks them under one icon. DSM uses `dev.voxhash.db-storage-manager` (`setDesktopFileName` + `StartupWMClass`). Re-run `./scripts/install-local-shims.sh`, fully quit both apps, and relaunch from the new `.desktop`. If Plasma still shows a stale group, restart the session. Stock launchers run separate processes — closing a ForexSmartBot/HandForge workspace *panel* does not kill DSM unless they share one process.

## Why is my backup smaller than the Dashboard total size?

The dashboard shows how much space the database occupies on disk (tables, indexes, TOAST, free space and bloat). A backup stores a logical dump of the data only, usually compressed. The Backups table shows both numbers and a tooltip explains the difference.

## Can I restore a backup from the app?

Yes, as an experimental opt-in feature: enable it in Settings → Backups & Adapters (or `DSM_EXPERIMENTAL=1`). It needs the `backups:restore` permission, a typed confirmation, passphrase for encrypted backups, and writes an audit log. It is off on stable by default. Automatic restore on a critical alert is intentionally not implemented; see [ROADMAP.md](../ROADMAP.md).

## Why is Google Drive not in the Backups adapter list?

It remains available as a library adapter only. Storing a long-lived OAuth token in a desktop form is riskier than S3 keys or an rclone remote, so Local, Proton Drive and S3 are the supported destinations.

## Is DB Storage Manager free? What do premium plugins cost?

The app and the built-in `migration` and `data_comparison` plugins are free. The first premium plugin, PITR Verify, and any later premium plugins are licensed through LicenseChain at deliberately low prices: US$1.99/month, US$16/year or US$24 one-time per plugin, and US$4.99/month, US$39/year or US$59 one-time for all of them. Updates are included while a subscription is active, or for the major version of a one-time licence. If the price is a barrier, write to contact@voxhash.dev. You can also donate at https://github.com/sponsors/VoxHash.

## Is there a REST API or web UI?

Not in the current release. The product is a desktop application with a Python package API for programmatic access. A web interface is on the longer-term roadmap.

## Why did Oracle installs used to fail?

Older docs and extras pointed at obsolete `cx_Oracle`, which always needed Oracle Instant Client. The project now uses **`oracledb`** (python-oracledb) in **Thin mode** by default — `pip install -e ".[oracle]"` with no Instant Client for Oracle Database 12.1+. Instant Client is only required for Thick mode (11g, NNE, AC/TAC); set `ORACLE_CLIENT_LIB_DIR`. See [installation.md](installation.md).

## What do I need for SQL Server?

`pip install -e ".[mssql]"` (`pyodbc`) plus Microsoft ODBC Driver 18 on the host (unixODBC on Linux/macOS). Details: [installation.md](installation.md).

## Which Python versions are supported?

`python_requires>=3.10`. Validated on 3.10–3.12. Prefer 3.12 for local development if your system default is newer (for example 3.14).

## What license is DB Storage Manager under?

**GPL-3.0-only** — see [LICENSE](../LICENSE). PyQt6 is GPL-3.0 or commercial (not LGPL); shipping the desktop app with free PyQt6 requires a GPL-compatible license. Comparable tools: Beekeeper Studio CE and HeidiSQL use GPL; DBeaver CE / CloudBeaver CE use Apache-2.0 (Eclipse/Java stack, not PyQt); pgAdmin uses the PostgreSQL License; Sequel Ace is MIT (Cocoa, no PyQt); Adminer is Apache-2.0 or GPL-2; DbVisualizer Free is proprietary (not OSS).

**Opsec note:** GPLv3 does **not** force you to publish private internal hardened deployments. Source obligations trigger on **conveyance** (distribution). We intentionally avoid AGPL so a private companion API deployment is not treated as a public network copyleft trigger. Distributing modified binaries to others still requires offering corresponding source under GPLv3.

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
