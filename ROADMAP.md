# Roadmap — DB Storage Manager

Status as of **1.0.5** (+ Dashboard customization on `main`, 2026-10-24). Items already shipped in-tree are marked accordingly; remaining work is prioritized for usability and reliability.

## Now (1.x patch / minor)

- Connection pooling for long-lived SQL engine sessions

## Next

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

- Dashboard customization: watched summary metrics + table column toggles, named saved layouts (Apply / Save / Save As / Delete / Reset), last-connection restore; SecureStore `dashboard_layout` prefs; unit + offscreen Qt smoke (`tests/test_dashboard_layout.py`) (post-1.0.5)
- Query Console optimization suggestions: **Analyze** button + suggestions table; SQL heuristics plus live EXPLAIN (SQLite `EXPLAIN QUERY PLAN`, Postgres/MySQL `EXPLAIN`) with Safe Mode SELECT-only respect; unit + offscreen Qt smoke (`tests/test_query_suggestions.py`) (post-1.0.5)
- Monitoring notification channels + threshold editing UI: Thresholds/Channels tabs, SecureStore-persisted `alert_thresholds` / `alert_channels`, `NotificationDispatcher` (desktop tray + in-app log) wired to AlertManager callbacks, threshold validation, query-time/disk-usage checks, unit + offscreen Qt smoke (post-1.0.5)
- Documentation kit synchronized with **1.0.5** release tags (README features/SSH/monitoring, docs index release alignment, i18n About strings, FAQ/configuration for optional live probes); gitignored sibling-DB fixture + `tests/test_real_connections.py` (post-1.0.5)
- Monitoring/alerts UX: status banner with health + alert counts, severity-colored alerts table with acknowledge/refresh, health detail column, timer-driven `DatabaseMonitor.poll_once()` wired to real collectors, AlertManager id/dedupe/counts, unit + offscreen Qt smoke tests (post-1.0.5)
- Connections UI SSH tunnel UX: bastion host/user/key/password/port fields, open/close status, Paramiko local port forward, encrypted `ssh_config` + SecureStore bastion index, unit tests with mocked network (post-1.0.5)
- Hardened optional engine installs: `oracledb` (Thin default / Instant Client only for Thick via `ORACLE_CLIENT_LIB_DIR`), clearer missing-driver `ImportError`s pointing at setup extras, SQL Server ODBC Driver 18→17 selection, platform Instant Client / ODBC docs (incl. Arch/Garuda helper), extras + missing-driver tests (1.0.5)
- Expanded automated tests: real SQLite driver/factory paths, SecureStore Fernet round-trips and failure cases, Safe Mode SELECT allow / non-SELECT block; CI `test` job runs `pytest -v tests/` as a hard gate (post-1.0.3)
- Optional Rust/PyO3 native helpers (`native/db_storage_native`) with pure-Python fallbacks (post-1.0.2)
- CI wheels for `db-storage-native` (Linux manylinux x86_64, Windows x64, macOS arm64) via `.github/workflows/native-wheels.yml`, attached to GitHub Releases on `v*` tags (1.0.3+; Intel macOS prebuilts dropped in 1.0.4 after macos-13 capacity stalls)

Feedback and proposals: https://github.com/VoxHash/DB_Storage_Manager/issues · contact@voxhash.dev
