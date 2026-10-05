# Roadmap — DB Storage Manager

Status as of **1.0.2** (2026-10-05). Items already shipped in-tree are marked accordingly; remaining work is prioritized for usability and reliability.

## Now (1.x patch / minor)

- Expand automated tests beyond import/smoke coverage (driver unit tests, SecureStore, Safe Mode)
- Harden optional engine installs (`oracle`, `mssql`, `clickhouse`, `influxdb`) and document Instant Client / ODBC prerequisites per platform
- Polish SSH tunnel UX in the Connections UI (Paramiko helpers already exist under `db_storage_manager.ssh`)
- Improve monitoring/alerts presentation using existing `monitoring/` modules
- Keep documentation kit synchronized with release tags

## Next

- Real-time monitoring refinements and actionable alerts
- Query optimization suggestions surfaced in the Query Console
- Dashboard customization (saved layouts / watched metrics)
- Connection pooling for long-lived SQL engine sessions
- Stronger backup verification (checksum / restore dry-run)

## Later

- Web UI / REST companion (desktop remains primary)
- Plugin marketplace and public SDK around `plugins/`
- Multi-user / RBAC for shared workstation deployments
- Deeper cloud-managed database integrations (RDS, Cloud SQL, Azure SQL) beyond current SDK stubs

## Explicitly out of scope for near-term

- Replacing the product name or Python package (`db_storage_manager` / `db-storage-manager`) — name is descriptive and already aligned with PyPI-style packaging
- Mobile companion app

Feedback and proposals: https://github.com/VoxHash/DB_Storage_Manager/issues · contact@voxhash.dev
