# Changelog — DB Storage Manager

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Public **plugin SDK** (`db_storage_manager.plugins.sdk`, API `1.0`): `Plugin` / `PluginMetadata` / `PluginType`, `plugin.json` manifest load/validate, documented authoring contract
- **Local plugin marketplace** (`LocalPluginMarketplace`): filesystem registry under user-data `plugins/`, sync built-ins (`migration`, `data_comparison`), install from path or http(s) zip/tar.gz, uninstall user installs, enable/disable via SecureStore `plugins.enabled`
- Desktop **Plugins** tab (View → Plugins / Ctrl+6): list registry, enable/disable, install from path/URL, uninstall
- Example third-party plugin `examples/plugins/hello_echo/` and tests (`tests/test_plugins_marketplace.py`)
- Local **Web UI / REST companion** (`db_storage_manager.api`): `GET /api/v1/health|info|connections|backups`, `POST …/verify` and `…/dry-run`, static glance UI at `/`; bind `127.0.0.1:8765` by default; optional `DSM_API_TOKEN` Bearer auth; passwords redacted; console script `db-storage-manager-api`
- Native helpers **zstd** compress/decompress and optional backup-file encryption offload (`encrypt_file` / `decrypt_file`); format `DSMENC1` = AES-256-GCM (1 MiB chunks) + PBKDF2-HMAC-SHA256 (200k iters); Rust path in `db_storage_native` 0.2.0 with Python fallbacks (`zstandard`, `cryptography`)
- Local backups support `compression="zstd"` and `encryption=True` + `encryptionKey` (passphrase never written to `.meta.json`); restore / dry-run decrypt then decompress
- Tests for zstd/encrypt round-trips and encrypted local backup create/restore/dry-run (`tests/test_backup_zstd_encrypt.py`); extended `tests/test_native.py`
- Stronger backup verification UX: Restore tab lists local backups with **Verify Checksum**, **Verify All**, and **Dry-run Restore**; color-coded PASS / FAIL / MISSING CHECKSUM status banner and table columns
- Local backup `.meta.json` sidecars persist SHA-256 (and related metadata) so `list_backups` reloads expected digests after restart
- `BackupManager.dry_run_restore`: real checksum verify, optional decrypt + gzip/zstd decompress to temp, SQLite header + `PRAGMA integrity_check` without writing to a live database
- Clearer `verify_backup_checksum` / `verify_backups_parallel` results (`status`: `pass` / `fail` / `missing_checksum` / `not_found`; missing stored digest is not treated as success)
- Unit tests for sidecar persistence, checksum pass/fail/parallel, gzip + SQLite dry-run, and offscreen Qt smoke (`tests/test_backup_verification.py`)
- SQL engine connection pooling (`db_storage_manager.db.pool.SQLEnginePool`): reuse long-lived sessions per connection profile, safe checkout/return, discard on profile delete, close on main-window shutdown
- `DatabaseConnectionFactory.acquire` / `release` / `shutdown_pool` wired into dashboard analysis, Query Console, enhanced query, backups, monitoring start/stop, and Connections test probe
- Real SQLite pool tests for reuse, exhaustion, context manager, discard, and shutdown (`tests/test_connection_pool.py`)
- Dashboard customization: **Customize dashboard** panel with watched summary metrics and table column toggles, named saved layouts (Apply / Save / Save As / Delete / Reset), and last-selected connection restore on restart
- SecureStore `dashboard_layout` settings (merged/normalized via `db_storage_manager.dashboard_prefs`); Settings save preserves dashboard prefs
- Unit tests for layout normalize/save/apply/delete + SecureStore round-trip and offscreen Qt restore-after-restart smoke (`tests/test_dashboard_layout.py`)
- Query Console **Analyze** action and optimization suggestions table: SQL heuristics (SELECT *, leading LIKE wildcards, missing WHERE, ORDER BY without LIMIT, etc.) plus live EXPLAIN analysis when a connection is available (SQLite `EXPLAIN QUERY PLAN`; Postgres/MySQL `EXPLAIN`), with Safe Mode blocking EXPLAIN for non-SELECT
- `db_storage_manager.analysis.query_suggestions` (`suggest_for_query`, `analyze_sql_heuristics`, `analyze_explain_plan`, `fetch_explain_plan`); suggestions also refresh after Execute using `explainPlan` from the result when present
- Unit tests with real SQLite EXPLAIN + offscreen Qt smoke for `QueryWidget` (`tests/test_query_suggestions.py`)
- Monitoring **Thresholds** and **Channels** tabs: editable warning/critical spinboxes for connection count, query time, cache hit ratio, and disk usage; desktop (system tray) + in-app notification channel toggles with live notification log
- `NotificationDispatcher` routes AlertManager emissions to enabled channels; `QSystemTrayIcon.showMessage` for real desktop notifications when a system tray is available
- Durable `alert_thresholds` / `alert_channels` in SecureStore settings (merged with defaults); Settings save preserves monitoring prefs
- `AlertManager.apply_thresholds` / `validate_thresholds`, constructor thresholds, and threshold checks for `queryTime` / `diskUsage` when present in metrics
- Tests for notification channels, threshold persistence, validation, and expanded offscreen Qt smoke (`tests/test_monitoring.py`)
- Optional live sibling-DB connection probes: gitignored `tests/fixtures/connections.local.json` (example template committed), `DSM_E2E_CONNECTIONS_FILE` / `DSM_E2E_CONNECT_TIMEOUT`, and `tests/test_real_connections.py` (SELECT-only `test_connection()`, skip when unreachable)
- Monitoring tab presentation: live status banner (health + alert counts), severity-colored alerts with source column, **Acknowledge Selected** / **Acknowledge All** / **Refresh Now**, health overall label + detail column, human-readable metric labels
- `DatabaseMonitor.poll_once()` for Qt-timer / script one-shot collect → health → threshold evaluation; `get_status_summary()` for banner data
- `Alert` stable `id`, `AlertManager.emit_alert` / `acknowledge_by_id` / `acknowledge_all` / `get_counts`, active-alert dedupe on threshold re-checks
- Unit tests for alerts + SQLite `poll_once`, offscreen Qt smoke for `MonitoringWidget` (`tests/test_monitoring.py`)
- Connections UI SSH tunnel workflow: enable bastion fields (host, port, user, password/passphrase, key path, remote host/port), **Open Tunnel** / **Close Tunnel** with live status, and Test Connection via local forward
- `SSHTunnel` local port-forward implementation (Paramiko `direct-tcpip`), `SSHTunnelError` / `normalize_ssh_config` / `validate_ssh_config`, sync + async `TunnelManager` APIs
- `SecureStore.upsert_ssh_settings_for_connection` / `remove_ssh_settings_for_connection` for encrypted bastion metadata in `ssh-keys.enc` (passwords remain only in `connections.enc`)
- Unit tests for SSH validation, mocked Paramiko connect/auth paths, TunnelManager lifecycle, and SecureStore SSH settings (`tests/test_ssh_tunnel.py`)

### Changed
- Documentation kit aligned with **1.0.5** (README features for SSH/monitoring, docs index release note, FAQ/configuration for E2E fixtures, i18n About strings → 1.0.5)
- Monitoring UI collects via timer-driven `poll_once()` instead of discarding a short-lived asyncio loop after `start_monitoring()`
- Health-failure alerts go through `AlertManager.emit_alert` (callbacks + dedupe) instead of a silent list append

### Fixed
- Shell scripts under `scripts/` use Unix LF line endings (`.gitattributes`: `*.sh text eol=lf`) so shebangs no longer fail with `env: ‘bash\r’: No such file or directory`
- Connections tab now loads persisted profiles on startup and closes SSH tunnels when the main window exits


## [1.0.5] - 2026-10-24

### Added
- `db_storage_manager.db.optional_deps` with shared missing-driver `ImportError` messages (extras + platform notes) for `oracle`, `mssql`, `clickhouse`, and `influxdb`
- Platform Instant Client / ODBC prerequisites in `docs/installation.md` (Linux including Arch/Garuda, macOS, Windows) and troubleshooting / FAQ updates
- Arch/Garuda host helper `scripts/setup-host-odbc-arch.sh` (unixODBC + AUR `msodbcsql` Driver 18)
- Tests for setup extras metadata, helpful ImportErrors when optional drivers are absent, and SQL Server ODBC driver preference (`tests/test_optional_engines.py`)
- `ORACLE_CLIENT_LIB_DIR` support to enable python-oracledb Thick mode when Instant Client is installed

### Changed
- Oracle extra / driver switched from obsolete `cx_Oracle` to **`oracledb`** (Thin mode by default; no Instant Client required for Oracle Database 12.1+)
- `.[engines]` extra now includes `oracledb` alongside `pyodbc`, `clickhouse-driver`, and `influxdb-client`
- SQL Server connections prefer **ODBC Driver 18**, then 17, then any installed SQL Server ODBC driver, with a clear error when none are registered
- Package version synchronized to `1.0.5`

## [1.0.4] - 2026-10-24

### Added
- Automated unit tests for SQLite driver/factory, SecureStore encrypt/decrypt round-trips and failure handling, and Safe Mode enforcement (`tests/test_sqlite_driver.py`, `tests/test_secure_store.py`, `tests/test_safe_mode.py`, shared `tests/conftest.py`)

### Changed
- CI `test` job runs `pytest -v tests/` as a failing gate (no longer swallowed); ensures `aiosqlite` / `cryptography` / `pytest` are installed for the unit-test baseline
- Native wheels CI builds macOS **arm64 only** (`macos-latest`); dropped `macos-13` Intel jobs that queued indefinitely and blocked release asset upload
- Release attach job uploads whatever platform artifacts exist (`fail-fast` already false; attach continues when a sibling job fails) so one platform cannot leave a tag with zero assets
- Package version synchronized to `1.0.4`

### Fixed
- `v1.0.3` GitHub Release had zero assets while Native wheels waited on macos-13 capacity; prebuilt Linux / Windows / macOS arm64 wheels and sdist were attached from completed jobs, and the workflow was fixed so future tags are not blocked the same way

## [1.0.3] - 2026-10-24

### Added
- Optional Rust/PyO3 native module (`native/db_storage_native`, import `db_storage_native`) for streaming gzip compress/decompress, SHA-256 checksums (including parallel batch hashing), numeric aggregation, and parallel row fingerprinting
- Python feature-detect wrapper `db_storage_manager.native` with pure-Python fallbacks when the extension is not built
- Local backups record `sha256` metadata; `BackupManager.verify_backup_checksum` / `verify_backups_parallel` for integrity checks
- `pip install -e ".[native]"` extra (maturin) and tests under `tests/test_native.py`
- CI workflow `.github/workflows/native-wheels.yml` builds manylinux / Windows / macOS wheels (and sdist) and attaches them to GitHub Releases on `v*` tags so end users can `pip install` the extension without a local Rust toolchain
- Roadmap entries for exploratory Android/GrapheneOS and Meta Quest 3 companion apps

### Changed
- Local backup gzip path and data comparison row matching use the native helpers when available
- Query performance statistics use native `aggregate_f64` and expose min/max execution times
- Native extension uses the Python stable ABI (`abi3-py310`) so one wheel per OS/arch covers CPython 3.10+
- Package version synchronized to `1.0.3`

## [1.0.2] - 2026-10-05

### Added
- Standardized documentation kit under `docs/` (index, getting started, quick start, installation, configuration, usage, CLI, API, architecture, troubleshooting, FAQ, and two working examples)
- Optional install extras in `setup.py` for `oracle`, `mssql`, `clickhouse`, `influxdb`, and bundled `engines`

### Changed
- Core `requirements.txt` no longer hard-requires `cx_Oracle`, `pyodbc`, `clickhouse-driver`, or `influxdb-client` so default installs succeed without Instant Client / ODBC
- Synchronized package version to `1.0.2` across `setup.py`, `db_storage_manager.__version__`, and `APP_VERSION`
- Corrected GitHub URLs and badges to `https://github.com/VoxHash/DB_Storage_Manager`
- Refreshed `ROADMAP.md` against the current codebase (removed dependency on deleted `DEVELOPMENT_GOALS.md`)
- Tightened `.gitignore` for caches, coverage, and local tooling while keeping required ignore coverage

### Fixed
- Restored corrupted `db_storage_manager/ssh/__init__.py` (null-byte file) to the valid SSH package exports
- Documented Python 3.10–3.12 as the validated install path after core install failures on system Python 3.14 when optional Oracle builds were required

### Removed
- Stray documentation outside the kit: `DEVELOPMENT_GOALS.md`, legacy `docs/GETTING_STARTED.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, and duplicate `docs/*_from-workstation-20260928.md` files (content folded into the kit / root `SECURITY.md`)

## [1.0.1] - 2026-03-12

### Changed
- Updated repository documentation structure
- Improved CI/CD workflows
- Enhanced `.gitignore` with comprehensive patterns

### Removed
- Removed `GITHUB_TOPICS.md` (topics are managed via GitHub UI)

### Fixed
- Fixed undefined `os` import in Oracle database restore functionality
- Release workflow executable artifact path corrections
- CI dependency installation fallback when `cx_Oracle` fails to build

## [1.0.0] - 2025-11-26

### Added
- Complete cross-platform desktop application built with PyQt6
- Multi-database support: PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis
- Storage analysis dashboard with comprehensive metrics and visualizations
- Secure connection management with encrypted credential storage (cryptography/Fernet)
- Advanced query console with multi-database query execution
- Safe mode to prevent accidental data modification
- Backup and restore system with Local, S3, and Google Drive adapters
- Scheduled backup automation
- Theme system and internationalization support
- Connection testing and validation
- Query explain plans where supported
- Encrypted backup storage and compression support
