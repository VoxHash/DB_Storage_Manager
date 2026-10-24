# Roadmap — DB Storage Manager

Status as of **1.0.4** (2026-10-24). Items already shipped in-tree are marked accordingly; remaining work is prioritized for usability and reliability.

## Now (1.x patch / minor)

- Harden optional engine installs (`oracle`, `mssql`, `clickhouse`, `influxdb`) and document Instant Client / ODBC prerequisites per platform
- Polish SSH tunnel UX in the Connections UI (Paramiko helpers already exist under `db_storage_manager.ssh`)
- Improve monitoring/alerts presentation using existing `monitoring/` modules
- Keep documentation kit synchronized with release tags

## Next

- Real-time monitoring refinements and actionable alerts
- Query optimization suggestions surfaced in the Query Console
- Dashboard customization (saved layouts / watched metrics)
- Connection pooling for long-lived SQL engine sessions
- Stronger backup verification UX (checksum / restore dry-run) on top of the native SHA-256 helpers already wired into local backups
- Extend native helpers to zstd compression and optional backup-file encryption offload

## Later

- Web UI / REST companion (desktop remains primary)
- Plugin marketplace and public SDK around `plugins/`
- Multi-user / RBAC for shared workstation deployments
- Deeper cloud-managed database integrations (RDS, Cloud SQL, Azure SQL) beyond current SDK stubs

## Future platforms (exploratory)

These are **not** near-term deliverables. Desktop (PyQt6) remains the product; mobile/XR would be companion surfaces that reuse connection profiles and read-only monitoring where feasible.

### Android / GrapheneOS companion

- **Goal**: privacy-respecting companion for GrapheneOS / stock Android — view encrypted connection inventory metadata, trigger scheduled backup status checks, and receive local alerts without shipping a full query console on-device
- **Prerequisites**: stable desktop API or export format for connection metadata; hardened credential model that never mirrors Fernet master keys to mobile storage by default
- **Approach (tentative)**: Kotlin + Jetpack; optional F-Droid / sideload builds first; GrapheneOS network permission hardening documented; no Google Play Services hard dependency
- **Out of scope initially**: running arbitrary SQL, full backup restore, or embedding database engines on-device

### Meta Quest 3 (OpenXR) companion

- **Goal**: spatial “ops glance” panel for lab/workstation operators — dashboard metrics and backup health in VR, not a primary DBA workstation
- **Prerequisites**: Web or lightweight companion backend from the Later “Web UI / REST” track; clear UX research that VR adds value over a phone glance view
- **Approach (tentative)**: Unity or WebXR client talking to a local companion service; Quest Store packaging only after privacy review
- **Out of scope initially**: immersive query editing, full schema management, or replacing the desktop app

## Explicitly out of scope for near-term

- Replacing the product name or Python package (`db_storage_manager` / `db-storage-manager`) — name is descriptive and already aligned with PyPI-style packaging
- Full mobile rewrite of the PyQt6 desktop UI
- Shipping Quest / Android apps before the Web/REST companion foundation exists

## Shipped recently

- Expanded automated tests: real SQLite driver/factory paths, SecureStore Fernet round-trips and failure cases, Safe Mode SELECT allow / non-SELECT block; CI `test` job runs `pytest -v tests/` as a hard gate (post-1.0.3)
- Optional Rust/PyO3 native helpers (`native/db_storage_native`) with pure-Python fallbacks (post-1.0.2)
- CI wheels for `db-storage-native` (Linux manylinux x86_64, Windows x64, macOS arm64) via `.github/workflows/native-wheels.yml`, attached to GitHub Releases on `v*` tags (1.0.3+; Intel macOS prebuilts dropped in 1.0.4 after macos-13 capacity stalls)

Feedback and proposals: https://github.com/VoxHash/DB_Storage_Manager/issues · contact@voxhash.dev
