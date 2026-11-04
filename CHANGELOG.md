# Changelog — DB Storage Manager

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Live restore rehearsal in CI**: `tests/test_live_restore.py` drives the real `create_backup` / `full_restore` path (encrypted zstd backup, drift, typed confirmation, safety backup, `pg_dump` + `pg_restore`, `mysqldump` / `mariadb-dump` + client) against live PostgreSQL and MySQL/MariaDB servers and compares schema, rows, indexes and views after the restore. `.github/workflows/live-restore.yml` runs it on PostgreSQL 14, 15 and 16 and MySQL 8.0 service containers; locally the tests skip unless `DSM_LIVE_PG_*` / `DSM_LIVE_MYSQL_*` point at a server whose account may create and drop databases (each test uses its own throw-away database). Findings from the rehearsal are listed under Fixed and Known limits
- **Bundle licences unlock every first-party premium plugin**: the licence gate now accepts a valid, active licence for any "all premium plugins" bundle product (monthly, yearly or one-time, `plugins.pricing.BUNDLE_PRODUCT_IDS`) for every plugin whose `license.product_id` is listed in `PREMIUM_PRODUCT_IDS` (`pricing.accepted_product_ids`). A first-party premium plugin is unlocked by any of its own monthly, yearly or one-time products regardless of which one its manifest lists (`pricing.accepted_product_ids`). Per-plugin product ids keep working unchanged, third-party plugins are never unlocked by a bundle, and free plugins never touch LicenseChain. The product id actually purchased is what SecureStore records. Known gap: the one-time bundle product has an empty description in the LicenseChain dashboard (not editable through the API from here)
- **Premium plugin licensing (LicenseChain)**: a plugin can declare an optional `license` block (`product_id`, optional `pricing`) in `plugin.json`. Keys are verified against the public LicenseChain API (`POST /v1/licenses/verify`, RS256 `license_token` checked with the published JWKS, purchase product matched through the hosted-checkout validate endpoint) and stored encrypted in SecureStore (`plugin-licenses.enc`). Verification happens before plugin code is imported, again on enable and on every execution, with a 24 h online re-check and a 7 day offline grace (`DSM_LICENSE_RECHECK_HOURS`, `DSM_LICENSE_GRACE_DAYS`). The built-in `migration` and `data_comparison` plugins and every plugin without a `license` block stay free. The Plugins tab gets a License column plus **Activate License…**, **Get License** and **Deactivate License**; all license events go to `audit.log` with the key masked. A malformed `license` block fails closed
- **Plugin pricing policy**: `plugins/pricing.py` documents the affordable first-party ceilings (single plugin US$1.99/month, US$16/year or US$24 one-time; all-plugins bundle US$4.99 / US$39 / US$59), `scripts/licensechain_products.py` turns a plugin's `license.pricing` into LicenseChain `POST /v1/products` bodies (dry run by default; `--apply` reads `LICENSECHAIN_API_KEY` from the environment and never prints it). The Plugins tab shows the price in the license prompt and a **Support DSM** button that opens https://github.com/sponsors/VoxHash
- **LicenseChain products provisioned**: 18 products created in the LicenseChain seller account (monthly / yearly / one-time for the all-plugins bundle and for each planned premium plugin: PITR verify, Schema drift, RLS audit, Pooler health, Encrypted export), priced per the policy above. Their ids are recorded in `plugins.pricing.PREMIUM_PRODUCT_IDS`; nothing is on sale until a premium plugin ships
- **Liquid-glass tokens and icons**: every theme carries glass tokens (top/bottom tint, highlight, edge shadow) used by the sidebar, nav pill and login card; QPainter stroke icons (`gui/icons.py`) for the sidebar and for icon-only Refresh / Edit buttons, with tooltips and accessible names. Destructive and experimental actions keep text labels
- **Reduce transparency**: Settings → General checkbox (and `DSM_REDUCE_TRANSPARENCY=1`) flattens glass surfaces to solid colours; visible focus rings on every button
- **Tests**: `tests/test_plugin_licensing.py` (real local HTTP stub of the LicenseChain contract with real RSA JWTs, plus one live-API check), `tests/test_plugin_pricing.py`, `tests/test_gui_modernization.py` (WCAG contrast, icons, accessibility, license UI)
- **Experimental full Restore Backup**: **Restore…** on the Backups tab (hidden unless enabled in Settings → Backups & Adapters or `DSM_EXPERIMENTAL=1`; default off). Requires `backups:restore` when RBAC is active (checked in the manager as well as the UI), a typed confirmation of the target database name, a passphrase for encrypted backups, and an optional encrypted safety backup of the current state. A pre-flight (SHA-256, decrypt, unpack, engine match) runs before anything is overwritten. Every attempt is appended to `audit.log` (JSON lines, mode `600`, secrets stripped). Works from Local, Proton Drive and S3 backups. Covered end-to-end by tests on SQLite; other engines go through their existing driver `restore_backup` (PostgreSQL / MySQL tooling) and are rehearsed against live PostgreSQL and MySQL servers by `tests/test_live_restore.py` (see below)
- **S3-compatible backup adapter** (AWS S3, MinIO, Cloudflare R2, Backblaze B2) via boto3: Backups adapter + **Configure S3…**, `DSM_S3_*` / `AWS_*` / SecureStore `s3_backup`, always DSMENC1-encrypted, checksum sidecars, verify / dry-run / restore parity with Proton Drive; tests run against a real moto S3 server
- **Shared backup pipeline** (`backups/pipeline.py`): one compress / encrypt / checksum path for every adapter
- **Backup size context**: backups record `dumpSize` and `sourceStorageBytes` (live database size at backup time). The Backups table has a **Source DB size** column, tooltips on size cells and a short explainer; the Dashboard **Total size** card explains that it is on-disk size including indexes and free space
- **Email alerts**: real SMTP channel (STARTTLS / SSL; plain only for loopback), minimum severity, per-alert cooldown, asynchronous delivery, `DSM_SMTP_*` overrides, password encrypted in SecureStore. The Monitoring **Email** checkbox is enabled only when the configuration is complete
- **`monitor` role**: on-call users with `monitoring:read` / `monitoring:write` and read access to connections, backups, settings and plugins, but no backup, restore or query rights
- **Watch on launch**: optional per-connection auto-start of monitoring so alerts arrive without clicking Start
- **Tests**: `tests/test_full_restore.py`, `tests/test_s3_backup.py`, `tests/test_email_alerts.py`, `tests/test_settings_ui.py`; `moto[server,s3]` added to the dev dependencies

### Changed
- **Settings** is now a tabbed page: General, Backups & Adapters, Notifications, Users & RBAC, Updates. Saving preserves keys owned by other tabs
- **Signed-in indicator**: the redundant bottom status bar is removed; the sidebar footer is the single indicator
- **Plugins**: built-in `data_comparison` and `migration` list **VoxHash** as author
- **Adapters**: Local, Proton Drive and S3 are supported in the UI. Google Drive stays library-only (no desktop OAuth-token form); a plugin / rclone path is tracked in the roadmap
- **Auto-restore on critical alerts** is deliberately not implemented (destructive, no safe unattended confirmation); rationale in the roadmap

### Fixed
- **PostgreSQL restore with a newer client than server**: a `pg_restore` newer than the server (for example client 18 into server 16) replays `SET transaction_timeout = 0`, which the server rejects, so `pg_restore` exited non-zero although everything was restored and the restore was reported as failed. `PostgreSQLConnection.restore_backup` now tolerates only errors that are all `unrecognized configuration parameter` on a `SET` statement; any other `pg_restore` error still fails the restore
- **Light theme contrast**: the warning colour is now `#B45309` (readable on the light background)
- **Light theme**: the Settings RBAC panel no longer keeps the dark stylesheet it was built with; scroll areas, hint labels and the Plugins enabled colour follow theme changes
- **Qt mnemonics**: labels such as "Backups & Adapters" and "Users & RBAC" no longer lose the ampersand
- **Backup overwrite**: a second backup created in the same second no longer replaces the first (collision-safe file names)
- **Stale connection pool**: editing a connection discards pooled sessions so restores and backups use the new settings

### Known limits
- **Restore replaces, it does not reconcile**: objects that exist only on the target are kept. PostgreSQL `pg_restore --clean` cannot drop a backed-up table while a table created after the backup still references it (for example rolling back to a safety backup after a restore recreated `orders`); the restore then fails loudly and the target keeps its current data. MySQL dumps recreate tables with foreign key checks off and are not affected. Rehearse into an empty or scratch database; a built-in scratch-database restore is tracked in the roadmap

## [1.0.7] - 2026-11-03

### Added
- **Concurrent GUI jobs**: new `gui/jobs.py` (`JobWorker` / `JobRunner`) - one active job per group, groups run in parallel. Backups (create / list / verify), Monitoring (start / poll / stop) and the update check run in worker threads so the window never freezes; the Rust native helpers are unchanged
- **System tray**: left click shows/hides the window, double click raises it, middle click opens Backups, right click opens a menu (Show/Hide, Dashboard / Backups / Monitoring, live monitoring + backup status lines, Changelog & Updates, Quit)
- **Notification auto-dismiss**: desktop notifications close after a configurable number of seconds (Settings, default 5, clamped 2-60). Some desktops treat the timeout as a hint
- **Changelog & Updates dialog** (Help menu, tray, Settings): shows `CHANGELOG.md` and checks the public GitHub Releases API on demand. Stable vs experimental channel (GitHub pre-releases). No auto-install and no private update server - it links to the release page and offers a `pip install ... @ git+https://github.com/VoxHash/DB_Storage_Manager.git@<tag>` command
- **Adapter-aware verification**: `BackupManager.verify_backup` / `verify_backups_parallel` verify Proton Drive rows through the adapter (rclone download + SHA-256) instead of treating remote targets as local paths
- **Dry-run passphrase prompt**: dry-run restore of an encrypted (DSMENC1) backup asks for the passphrase (the encryption field is used first); it is never stored
- **RBAC**: new `query:write` permission; Query Console and Monitoring enforce `query:*` / `monitoring:*` permissions; login throttle (5 failures, 60 s lockout) for the desktop and API Basic auth
- **Scheduler passphrase vault**: scheduled-backup passphrases are kept in the encrypted SecureStore file `scheduled-backup-secrets.enc`; legacy plaintext `encryptionKey` entries in `scheduled-backups.json` are migrated automatically
- **Translations**: all 11 locales are complete (previously ~208 keys were English-only in every non-English locale) including Chinese Settings / Backups / Monitoring / Plugins / RBAC / tray / updates / schedule strings; `tests/test_v107_features.py` audits key parity and placeholders

### Fixed
- **Raw i18n key in Settings (Chinese)**: `backups.proton_ready` no longer shows as a raw key - lookups fall back to English per key before showing the key, and every locale now carries the key
- **Verify All NOT_FOUND** for valid Proton Drive or local rows
- **Scheduled Backups**: the Connection dropdown is populated; add / list / toggle / remove covered by tests; schedules run on a private `schedule.Scheduler` with per-schedule run locks (no overlapping runs) and a bounded number of concurrent dumps
- **Monitoring false criticals** (`InterfaceError (0, '')`): MySQL/MariaDB sessions are revived with `ping(reconnect=True)` (full reconnect fallback) and the health check reconnects once before reporting a failure
- **Packaging**: `package_data` now ships the translation JSON files and the API static UI (a pip-installed copy previously had neither)
- **Backups**: removed technical busy text (Create Backup shows only "Creating backup…"; Scheduled Backups help shows only "Schedule recurring dumps."); removed "Built with Python and PyQt6." from About; About shows the real version (was hard-coded 1.0.5) and © 2026
- **Tests**: tests no longer read or write the developer's real RBAC state or language preference; pooled SQL engine threads are closed at session end
- **Backups UI freeze (“Not Responding”)**: Create / refresh / verify / dry-run no longer call blocking `asyncio.run` / rclone on the Qt GUI thread; work runs in `BackupJobWorker` (`QThread`) so Proton uploads and large SSH dumps keep the window responsive
- **Proton Drive rclone draft / 502 / 422**: transfer uploads use `--protondrive-replace-existing-draft=true` plus higher retries; on draft/name conflict, `deletefile` once and retry `copyto`; default rclone timeout raised to 900s for large dumps
- **Scheduled Backups tab**: wired to `ScheduledBackupManager` (add / enable-disable / remove / refresh); jobs tag by schedule id so stopping one does not clear others; Proton schedules require DSMENC1 passphrase in adapter config
- **Linux window identity (vs Telegram Multi-Account Message Sender)**: migrate FreeDesktop / Wayland app id to reverse-DNS `dev.voxhash.db-storage-manager` (matching `StartupWMClass` and Qt `setDesktopFileName`) so KDE/Plasma no longer groups or closes this process with sibling Python GUIs that previously shared generic `python3`. Org domain stays `db-storage-manager.voxhash.dev`; user data remains `~/.config/db-storage-manager/`. `scripts/install-local-shims.sh` installs the new `.desktop` and removes the legacy `db-storage-manager.desktop`. Closing a Plasma/workspace panel still only closes windows that share that host process — DSM is a separate process when launched via its own entry point.

### Changed
- **Opsec**: Proton Drive Create Backup forces DSMENC1 encryption (checkbox locked on); encryption before rclone upload remains the enterprise default for cloud destinations
- **Release workflow**: `release.yml` artifact names (Windows `.exe`, macOS binary / `.dmg`, Linux `.AppImage`) now use the pushed tag (`github.ref_name`) instead of a stale hard-coded `v1.0.1`
- **README**: documents installing a tagged release with `pip install "db-storage-manager @ git+https://github.com/VoxHash/DB_Storage_Manager.git@v1.0.7"` and the notification auto-dismiss setting

## [1.0.6] - 2026-11-02

### Fixed
- **Linux window identity**: set unique FreeDesktop desktop-file id via Qt `setDesktopFileName` so Wayland/KDE no longer treats the app as generic `python3` and groups or closes it with sibling VoxHash Python GUIs (e.g. Telegram Multi-Account Message Sender).

## [1.0.5]

### Fixed
- **Proton Drive Create Backup missing rclone remote section**: when SecureStore / `.env.protondrive.local` had username+password (and optional OTP / 2FA / mailbox password) but `~/.config/rclone/rclone.conf` had no `[protondrive]` section, Create Backup still ran `rclone mkdir protondrive:…` and failed with “didn't find section in config file”. Adapter now `rclone obscure`s secrets, writes a mode-600 ephemeral rclone.conf, passes `--config` for mkdir/copyto/list/delete, and deletes the temp file afterward; remote paths with spaces (e.g. `DB Storage Manager`) stay a single argv element
- **Proton Drive Create Backup Errno 2 on unsafe connection names**: Proton `_prepare_payload` built `/tmp/dsm-proton-<rand>/<connection>_TIMESTAMP.backup` from the raw label, so names with `/` (Postgres pooler `…/postgres`, SSH/MySQL `vps/prod…`) nested under the temp dir and failed before DSMENC1 encrypt / rclone upload. Reuse `sanitize_backup_basename` + `mkdir(parents=True, exist_ok=True)` like Local; remote object names stay a single path segment
- **Proton Drive “not configured” with local env / desktop PATH**: load gitignored `.env.protondrive.local` (and package-root / `~/.config/db-storage-manager/` copies) like cloud dotenv; resolve rclone via `~/.local/bin/rclone` and other common paths when desktop launchers omit user bin from `PATH`; treat SecureStore `proton_drive` username+password or an rclone remote as ready so the Backups orange banner clears
- **Settings wipe of Proton / cloud prefs**: saving theme/language no longer drops `proton_drive`, `cloud_managed`, or `companion` from SecureStore
- **Local Create Backup Errno 2 on long Supabase names**: backup filenames derived from connection labels with spaces, em dashes (`—`), parentheses, or `/` (e.g. `…supabase.com/postgres`) were treated as nested paths, so copy/encrypt failed with `No such file or directory`. Sanitize to a single filesystem-safe segment (hash suffix for uniqueness), and `mkdir(parents=True, exist_ok=True)` before dump/encrypt/meta writes
- **MySQL dump CLI missing**: `create_backup` / `restore_backup` resolve `mariadb-dump` then `mysqldump` (and `mariadb` then `mysql` for restore) so MariaDB 11+ deprecation-as-`mysqldump` does not fail backups; raise a clear `FileNotFoundError` with Arch/Garuda install hint (`sudo pacman -S --needed mariadb-clients`) when neither is on PATH
- **Local backup TypeError (SSH/MySQL + encryption)**: `BackupManager` treated dump results as dicts (`result["path"]`) while MySQL/Postgres returned a bare path string, causing `Backup failed: string indices must be integers, not 'str'`. Normalize str/Path/dict dump results; MySQL/Postgres now return `{"path", "size"}`; open SSH tunnels before dump/restore like Dashboard/Query
- **Backups UI Proton status gating**: Proton Drive “not configured” / missing-rclone banners no longer show on Create when Adapter is Local, or on Restore while listing local backups; status appears only when Adapter is Proton Drive or after **Refresh Proton Drive** (Local create/restore/verify no longer depend on rclone)
- **Dashboard Analyze (Postgres/Supabase)**: storage analysis now discovers relations only via `pg_catalog.pg_class` OIDs (sizes + `reltuples` estimates) — no per-table `COUNT(*)` and no hardcoded relation names (fixes `relation "public.clientvault" does not exist`)
- **Dashboard / Monitoring / Query SSH**: open or reuse `TunnelManager` local forward before driver connect (same pattern as Connections test / import probe); shared process-wide tunnel manager via `get_shared_tunnel_manager()` + `ensure_tunnel_for_connection`
- **MySQL/MariaDB Analyze**: table sizes from `information_schema.TABLES` (`DATA_LENGTH` / `INDEX_LENGTH`); index listing from `STATISTICS` without invalid `index_length` (fixes `1054 Unknown column 'index_length'`)
- **Monitoring health**: ping with `SELECT 1` without disconnecting the live session; critical alerts include check failure summaries instead of a generic unhealthy string; latency thresholds tolerate SSH/remote RTT (healthy under 500ms) so normal tunnel lag is not a false critical

### Changed
- **License**: project relicensed from MIT to **GPL-3.0-only** for coherence with PyQt6’s GPL-or-commercial dual license when distributing the free PyQt6 wheels; LICENSE, README badge/section, `setup.py` classifiers, native crate metadata, and FAQ updated accordingly

### Added
- **In-app Proton Drive configuration**: Settings and Backups **Configure Proton Drive…** dialog saves username / password / optional OTP into encrypted SecureStore (`proton_drive`); `save_proton_drive_credentials` helper; setup script `scripts/setup-protondrive-env.sh` (interactive TTY or documented non-interactive copy of `.env.protondrive.local.example`)
- Unit tests for SecureStore credential detection, dotenv load, rclone path fallback, and rclone.conf section detection (`tests/test_proton_drive_backup.py`)
- **Connection importers** (`db_storage_manager.importers`): parse platform `.env` (`DATABASE_URL` / `DIRECT_URL` / `DB_*` / `POSTGRES_*` / `MYSQL_*` / Supabase) and SSH key folders (`KEY` + optional `SSH.pub` / `VPS.txt` / `DB.txt`) into `ConnectionConfig` profiles; prefer key path references; OAuth platform guides document grant-permissions flows that need user tokens
- Connections UI **Import from .env…** / **Import SSH key…**; REST `POST /api/v1/connections/import/env`, `POST /api/v1/connections/import/ssh`, `GET /api/v1/connections/import/platforms` (responses redacted)
- SecureStore merge helper + probe (`test_connection` / SSH tunnel); e2e script `scripts/import_connections_e2e.py`; unit fixtures + optional live pytest (`DSM_E2E_IMPORT=1`); gitignore for import dumps
- Docs: usage / configuration / API import sections
- **Application icon**: original SVG + PNG sizes (16–512) and Windows ICO under `db_storage_manager/resources/icons/`; `QApplication.setWindowIcon` plus MainWindow / LoginDialog; packaged via `setup.py` / `MANIFEST.in`; Linux `.desktop` (`packaging/linux/db-storage-manager.desktop`) and hicolor install via `scripts/install-local-shims.sh`; PyInstaller `icon=` + datas; offscreen load test (`tests/test_app_icon.py`)
- **Android / GrapheneOS companion foundation**: Kotlin sideload debug APK under `companions/android/` (no Play Services) calling local REST `health` / `connections` / `backups` with Bearer auth; token in EncryptedSharedPreferences
- **Companion privacy / credential-export review** ([docs/privacy-companion.md](docs/privacy-companion.md)): Fernet master keys never mirrored to mobile; sanitized `dsm-companion-export` format; plaintext secrets require `--include-secrets --i-consent`
- **SecureStore pairing token**: `db-storage-manager-pair` / `python -m db_storage_manager.security.pairing` stores SHA-256 only; REST companion accepts env `DSM_API_TOKEN` or pairing Bearer
- **Export CLI**: `db-storage-manager-export` / `python -m db_storage_manager.export.companion` writes mode-600 JSON inventory
- Tests for pairing, redacted export, and API pairing Bearer (`tests/test_companion_export_pairing.py`); Android build/sideload docs updated

### Changed
- Desktop main window is freely resizable (grow and shrink): replaced the hard `1200×800` minimum with a small floor of **800×500** (sidebar + usable content), no maximum size; shell/tab layouts use Expanding policies and stretch so tables, splitters, and page content reflow; login dialog size unchanged and does not constrain the main window after sign-in
- Theme switches re-apply glass panel stylesheets so Atmospheric / Light / Dracula updates MetricCard / PageTitle ink on every polished tab (no stale Atmospheric colors after Settings theme change); Plugins tab root is `#glassmorphism` like the other six sections
- Desktop **per-tab content polish** on the modern shell: shared page headers, dashboard metric cards, denser inventory tables, consistent margins/spacing across Dashboard / Connections / Query / Backups / Monitoring / Plugins / Settings — RBAC, plugins, monitoring, backups, query, and cloud discover behavior unchanged
- Desktop **modern shell**: library-style left navigation (hidden top tab bar), refined Atmospheric / Light / Dracula design tokens, cohesive stylesheet for menus, tables, inputs, primary CTAs, and polished sign-in card — RBAC, plugins, monitoring, backups, connections, and query console behavior unchanged
- GCP cloud extra uses PyPI package `google-cloud-sql` (imports `google.cloud.sqladmin_v1`); docs/tests/error strings updated from the obsolete `google-cloud-sqladmin` name
- Glassmorphism panel stylesheet targets `QWidget#glassmorphism` only (no longer boxes every nested child)

### Added
- Live theme visual pass: WCAG-style token contrast, Atmospheric / Light / Dracula × seven tabs with `QWidget.grab` property assertions, optional on-screen post-login smoke when `DISPLAY` is set (`tests/test_tab_content_polish.py`, `tests/test_gui_shell.py`); PNG grabs under gitignored `artifacts/`
- GUI chrome helpers in `db_storage_manager.gui.utils`: `make_page_header`, `make_metric_card`, `configure_dense_table`, `apply_page_layout`; stylesheet tokens for `PageTitle` / `PageSubtitle` / `MetricCard` / `DenseTable`
- Dashboard summary metrics render as elevated cards (caption + value); Connections list uses denser rows with live profile count in the page subtitle
- Offscreen Qt smoke for tab content polish (`tests/test_tab_content_polish.py`)
- **Platform guides**: [docs/desktop.md](docs/desktop.md) (production PyQt6 client), [docs/android-grapheneos.md](docs/android-grapheneos.md) and [docs/quest.md](docs/quest.md) (honest interim browser→API paths; no native APK/Quest app yet), [docs/cross-platform.md](docs/cross-platform.md) (shared SecureStore / RBAC / `DSM_API_TOKEN` / bind+TLS opsec); linked from docs index, README, and ROADMAP
- **Cloud credential helper** `scripts/setup-cloud-env.sh`: creates gitignored `.env.cloud.local` (mode 600) wired to vendor default credential chains without inventing static keys; prints host credential presence and discovery readiness without secret values
- **Cloud-managed database integrations** (`db_storage_manager.cloud`): deepened AWS RDS, GCP Cloud SQL, and Azure SQL beyond stubs — paginated discovery, connection-profile import, SSL guidance, RDS IAM `generate_db_auth_token`, Azure Entra access tokens for ODBC, clear `CloudSDKMissingError` / `CloudNotConfiguredError` when SDKs or credentials are missing
- Credentials from SecureStore `cloud_managed`, `.env.cloud.local`, or env (`DSM_AWS_*` / `DSM_GCP_*` / `DSM_AZURE_*`); never committed — `.env.cloud.local.example` shipped
- Connections UI **Discover Cloud…** dialog (status, refresh, multi-select import with password or IAM/Entra auth mode); PostgreSQL / MySQL / SQL Server drivers apply cloud auth/SSL from `ConnectionConfig.extra`
- Setup extras `aws`, `gcp`, `azure`, `cloud`; unit tests at SDK boundaries with optional live skip (`tests/test_cloud_managed.py`)
- **Proton Drive cloud backup** adapter (`db_storage_manager.backups.protondrive`): real upload/list/download/delete/verify via rclone `protondrive` remote; prefers DSMENC1-encrypted payloads + SHA-256 sidecar before upload; credentials from SecureStore `proton_drive`, `.env.protondrive.local`, or env (`DSM_PROTONDRIVE_*` / `RCLONE_PROTONDRIVE_*`) — never committed; `ProtonDriveNotConfiguredError` when rclone or account config is missing
- Backups UI: destination selector (Local / Proton Drive), encryption passphrase field, Proton status line, and **Refresh Proton Drive** list/verify/dry-run path
- `.env.protondrive.local.example` plus configuration/usage/installation docs for live rclone setup
- Unit tests with an in-memory rclone test double at the HTTP/rclone boundary (`tests/test_proton_drive_backup.py`)
- Offscreen Qt shell smoke tests for main window navigation + login, plus post-sign-in click-through of all seven nav sections and Atmospheric / Light / Dracula theme rotation (`tests/test_gui_shell.py`)
- **Multi-user / RBAC** for shared workstation deployments: local accounts with PBKDF2-HMAC-SHA256 password hashes in encrypted `users.enc`, roles `admin` / `user` / `viewer` / `guest`, and real permission checks on connections, backups, settings, plugins, and the REST companion
- Desktop **sign-in** when RBAC is active; Settings **Users & RBAC** panel to bootstrap the first admin, add users, change roles, reset passwords, enable/disable, and delete (with last-admin guards)
- CLI bootstrap: `db-storage-manager-bootstrap` / `python -m db_storage_manager.security.bootstrap` (`DSM_BOOTSTRAP_USERNAME` / `DSM_BOOTSTRAP_PASSWORD`)
- Optional TOTP MFA (pyotp) after password; API accepts HTTP Basic (local user) or `DSM_API_TOKEN` Bearer as system admin when RBAC is on
- Tests for hashing, open-mode vs enforced RBAC, viewer denials, MFA, API 401/403, and offscreen Qt smoke (`tests/test_rbac.py`)
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
