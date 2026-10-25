# Roadmap — DB Storage Manager

Status as of **1.0.5** (+ multi-user RBAC on `main`, 2026-10-25). Items already shipped in-tree are marked accordingly; remaining work is prioritized for usability and reliability.

## Now (1.x patch / minor)

_(clear — promote from Next when starting the next deliverable)_

## Next

- Deeper cloud-managed database integrations (RDS, Cloud SQL, Azure SQL) beyond current SDK stubs
- Optional per-tab content polish (dashboard cards, connection list density) on top of the shipped modern desktop shell

## Later

_(open — promote from Future platforms only when prerequisites land)_

## Future platforms (exploratory)

These are **not** near-term deliverables. Desktop (PyQt6) remains the product; mobile/XR would be companion surfaces that reuse connection profiles and read-only monitoring where feasible.

### Android / GrapheneOS companion

- **Goal**: privacy-respecting companion for GrapheneOS / stock Android — view encrypted connection inventory metadata, trigger scheduled backup status checks, and receive local alerts without shipping a full query console on-device
- **Prerequisites**: stable desktop API or export format for connection metadata; hardened credential model that never mirrors Fernet master keys to mobile storage by default
- **Approach (tentative)**: Kotlin + Jetpack; optional F-Droid / sideload builds first; GrapheneOS network permission hardening documented; no Google Play Services hard dependency
- **Out of scope initially**: running arbitrary SQL, full backup restore, or embedding database engines on-device

### Meta Quest 3 (OpenXR) companion

- **Goal**: spatial “ops glance” panel for lab/workstation operators — dashboard metrics and backup health in VR, not a primary DBA workstation
- **Prerequisites**: Web or lightweight companion backend from the shipped Web UI / REST companion; clear UX research that VR adds value over a phone glance view
- **Approach (tentative)**: Unity or WebXR client talking to a local companion service; Quest Store packaging only after privacy review
- **Out of scope initially**: immersive query editing, full schema management, or replacing the desktop app

## Explicitly out of scope for near-term

- Replacing the product name or Python package (`db_storage_manager` / `db-storage-manager`) — name is descriptive and already aligned with PyPI-style packaging
- Full mobile rewrite of the PyQt6 desktop UI
- Shipping Quest / Android apps before the Web/REST companion foundation exists

## Shipped recently

- Modern desktop shell: library-style left nav, Atmospheric dark theme tokens, cohesive PyQt6 stylesheet, polished RBAC sign-in card; offscreen smoke in `tests/test_gui_shell.py` (post-1.0.5)
- Multi-user / RBAC for shared workstations: PBKDF2 password hashes in encrypted `users.enc`, roles (`admin` / `user` / `viewer` / `guest`) with real permission checks (not always-allow), SecureStore persistence, desktop login when accounts exist, Settings **Users & RBAC** admin UI, `db-storage-manager-bootstrap` / `python -m db_storage_manager.security.bootstrap`, API Basic auth + Bearer system-admin when RBAC active, enforcement on connections / backups / settings / plugins / companion endpoints; tests in `tests/test_rbac.py` (post-1.0.5)
- Plugin marketplace and public SDK around `plugins/`: `plugins.sdk` (API `1.0`, `plugin.json` manifest), `LocalPluginMarketplace` (local registry, enable/disable via SecureStore, install from path or http(s) zip/tar.gz), desktop **Plugins** tab, example `examples/plugins/hello_echo/`, tests (`tests/test_plugins_marketplace.py`) (post-1.0.5)
- Web UI / REST companion (`db_storage_manager.api`): stdlib `ThreadingHTTPServer` on `127.0.0.1:8765`, optional `DSM_API_TOKEN` Bearer auth, sanitized connections, local backup list/verify/dry-run, minimal glance Web UI; `db-storage-manager-api` / `python -m db_storage_manager.api` (`tests/test_api_companion.py`) (post-1.0.5)
- Native zstd compress/decompress + optional backup-file encryption offload (`DSMENC1` AES-256-GCM + PBKDF2-HMAC-SHA256; Rust/PyO3 with `zstandard` / `cryptography` Python fallbacks); wired into local create/restore/verify/dry-run; `db_storage_native` 0.2.0 (`tests/test_backup_zstd_encrypt.py`, `tests/test_native.py`) (post-1.0.5)
- Stronger backup verification UX: local `.meta.json` SHA-256 sidecars, `BackupManager.verify_backup_checksum` / `verify_backups_parallel` status fields, `dry_run_restore` (checksum → optional gzip decompress → SQLite header + `PRAGMA integrity_check`), Restore tab Verify Checksum / Verify All / Dry-run Restore with pass/fail coloring; unit + offscreen Qt smoke (`tests/test_backup_verification.py`) (post-1.0.5)
- SQL engine connection pooling: `SQLEnginePool` with checkout/release, per-profile max size, close on app shutdown; wired through `DatabaseConnectionFactory.acquire` / `release` into dashboard, query, backups, monitoring, connections probe; real SQLite pool tests (`tests/test_connection_pool.py`) (post-1.0.5)
- Dashboard customization: watched summary metrics + table column toggles, named saved layouts (Apply / Save / Save As / Delete / Reset), last-connection restore; SecureStore `dashboard_layout` prefs; unit + offscreen Qt restore-after-restart smoke (`tests/test_dashboard_layout.py`) (post-1.0.5)
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
