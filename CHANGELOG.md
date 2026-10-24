# Changelog — DB Storage Manager

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
