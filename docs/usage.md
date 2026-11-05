# Usage

## Connections

1. Open **Connections**
2. Add a profile with type, name, and credentials (or SQLite path), **or** use one of the import affordances:
   - **Discover Cloud…** — AWS RDS / GCP Cloud SQL / Azure SQL from cloud APIs
   - **Import from .env…** — Supabase / Laravel / Prisma-style `DATABASE_URL`, `DIRECT_URL`, `DB_*`, `POSTGRES_*`, `MYSQL_*`
   - **Import SSH key…** — private `KEY` (or folder with `KEY` + optional `SSH.pub` / `VPS.txt` / `DB.txt`) for bastion tunnels
3. **Test Connection** before saving
4. Credentials are written to `connections.enc` through `SecureStore`

Supported types in the UI factory: `postgresql`, `mysql`/`mariadb`, `sqlite`, `mongodb`, `redis`, `oracle`, `sqlserver`/`mssql`, `clickhouse`, `influxdb`.

Cloud discovery needs provider credentials (see [configuration.md](configuration.md) and `.env.cloud.local.example`). Imported profiles can use password auth or IAM / Microsoft Entra tokens (`extra.auth_mode`). Clear errors are raised when SDKs or credentials are missing.

Platform “Connect with OAuth / grant permissions” flows need a registered OAuth client and user tokens — those are documented in `db_storage_manager.importers.oauth_platforms` and are **not** fully automated yet. Prefer exporting a project `.env` or importing SSH keys until tokens are configured. See [configuration.md](configuration.md#importing-connections).

Unsupported types raise `ValueError: Unsupported database type: ...` from `DatabaseConnectionFactory`.

## Storage analysis

1. Select a connection on the **Dashboard**
2. Run **Analyze**
3. Review `totalSize`, `tableCount`, `indexCount`, table list, and largest table metadata returned by each driver’s `analyze_storage()`

Large databases may take longer; analysis runs through async drivers bridged into the Qt UI.

## Query console

1. Open **Query Console**
2. Select a connection
3. Write SQL/NoSQL appropriate to the engine
4. Leave **Safe Mode** on unless you intentionally need writes

Safe mode behavior (SQLite and SQL-like drivers): non-SELECT statements raise `ValueError` such as `Only SELECT queries are allowed in safe mode`.

## Backups

Adapters:

- **Local** — files under the user data `backups/` directory, or the directory set in Settings → Backups & Adapters
- **S3** — S3-compatible (AWS, MinIO, R2, B2): bucket + credentials in Settings or `DSM_S3_*`; always encrypted
- **Google Drive** — API-only adapter, not offered in the desktop UI (see [configuration.md](configuration.md#s3-compatible-backups))
- **Proton Drive** — uploads via rclone `protondrive` remote (credentials from `.env.protondrive.local` / SecureStore / env; never commit secrets)

On the **Backups** tab:

1. **Create Backup** — pick a connection, adapter (Local or Proton Drive), compression, and encryption passphrase. Proton Drive **always** encrypts with DSMENC1 before rclone upload (enterprise opsec); Local can optionally encrypt. Create / refresh / verify / dry-run run on a background `QThread` so long SSH dumps and Proton uploads do not freeze the window.
2. **Restore** — **Refresh** lists local backups; **Refresh Proton Drive** and **Refresh S3** list remote objects when that destination is configured. **Delete…** (or right-click the row) removes the selected local archive and its checksum sidecar, or the Proton Drive / S3 object. It asks for confirmation and needs `backups:create`.
3. **Verify Checksum** / **Dry-run Restore** work on local rows; for Proton Drive rows the app downloads to a temp file, verifies SHA-256 against the `.meta.json` sidecar, then cleans up.
4. **Scheduled Backups** — add interval jobs (connection + Local/Proton + passphrase), then enable/disable or remove them from the table. Each due schedule runs in its own worker thread (a schedule that is still running is skipped, at most two dumps run at once). Definitions live in `scheduled-backups.json`; passphrases are stored only in the encrypted `scheduled-backup-secrets.enc`.
5. **Dry-run Restore** of an encrypted backup prompts for the passphrase (the encryption field is used first); it is not stored. **Verify All** checks local files natively and Proton Drive rows through the adapter.
6. **Sizes** — the **Size** column is the stored file (compressed and possibly encrypted); **Source DB size** is the live database size when the backup ran. Hover either cell for the breakdown. They differ by design: the live size counts table pages, indexes, TOAST and free space, while a dump stores logical data only (no index pages, no bloat), so a backup smaller than the Dashboard **Total size** is normal.
7. **Restore…** is on unless Settings → Backups & Adapters unchecks it (`DSM_EXPERIMENTAL=1` forces it on). It needs `backups:restore`. Choose the target connection, type the database name to confirm, keep an encrypted safety backup of the current state, and enter the passphrase for encrypted backups. A pre-flight check (checksum, decrypt, unpack) runs before anything is overwritten, and the outcome is written to the audit log. Tick **Rehearse into a new scratch database** and type `SCRATCH` to restore into a new SQLite file or a new PostgreSQL/MySQL database; the production database is not modified and no safety backup is taken.

Proton Drive is not configured until rclone is installed and either an rclone remote exists, SecureStore has username+password (**Configure Proton Drive…**), or `DSM_PROTONDRIVE_USERNAME` + `DSM_PROTONDRIVE_PASSWORD` are set via `.env.protondrive.local` / `./scripts/setup-protondrive-env.sh` — the UI shows a clear status line (orange when not ready) instead of a fake local path. rclone transfers use `--protondrive-replace-existing-draft=true` and retry on draft/422 conflicts (Proton 502 spikes are retried with a longer timeout).

## System tray, notifications and updates

- **Tray**: left click shows/hides the window, double click raises it, middle click opens **Backups**, right click opens the menu (Show/Hide, Dashboard / Backups / Monitoring, live status lines, **Changelog**, **Check for updates**, **Sign out** while a local account is signed in, **Quit**). **Sign out** ends the RBAC session and opens the same sign-in dialog as startup; cancelling that dialog quits. Closing the main window hides it to the tray and leaves the process running, and the window size is restored on the next launch. **Quit** on the tray menu is what exits. If the desktop has no system tray, closing the window still quits.
- **Notifications**: monitoring alerts raise desktop notifications that auto-dismiss after **Notification auto-dismiss** seconds (Settings, default 5).
- **Updates** (Settings → Updates, Help → Check for updates, About → Check for Updates...): channel, automatic check, and on demand the public GitHub Releases for a newer **stable** or **experimental** (pre-release) version. Nothing is downloaded or installed. **Changelog** (the button on that tab, Help → Changelog, and the tray) opens the local changelog in its own window and does not contact GitHub. **Check for updates automatically** is off until you turn it on, and then runs at most once every 24 hours.
- **Save Settings** sits at the bottom right on General, Backups & Adapters, Notifications and Updates. It is hidden on Users & RBAC, because those buttons save immediately.
- **Retention** (Settings → Backups & Adapters) is off by default. Keep N daily and M monthly. A connection can override the default. Pruning runs after a scheduled backup for Local, Proton Drive and S3.

## Themes and language

Use **Settings** to switch theme and language. Theme application goes through `themes.manager` and `gui.utils.apply_theme_to_app`.

## Monitoring and alerts

1. Open **Monitoring**
2. Select a saved connection and click **Start Monitoring**
3. The status banner shows overall health and active alert counts (critical / warning / info)
4. **Metrics**, **Alerts**, **Performance**, and **Health** tabs refresh every 5 seconds from the real `monitoring/` collectors (not placeholders)
5. On **Alerts**, select rows and **Acknowledge Selected**, or **Acknowledge All**; **Refresh Now** forces an immediate poll

6. **Channels**: desktop, in-app, **Email**, **Webhook**, **Slack**, **Discord**, and **Telegram**. Each remote channel is off until Settings → Notifications has a valid configuration. Discord is an incoming webhook URL. Telegram is a bot token and chat id; the app posts only to `api.telegram.org`. Secrets stay in SecureStore and are not written to the notification log. Users with the `monitor` role can run all of this; enable **Start monitoring on launch** to watch a connection as soon as the app opens. **Install** `connection-email-alerts` for SMTP that belongs to one connection, and `multi-connection-monitor` to health-check several opted-in connections from the same process. Both are configured on **Monitoring → Channels** after they are installed and enabled. Saving the profile or the watch list needs `settings:write` (an admin). Until a connection profile is enabled, or at least one connection is checked, an enabled plugin does not send mail and does not poll.

Thresholds (connection count, cache hit ratio, health failures) live in `AlertManager`. SQLite reports basic connectivity metrics; PostgreSQL / MySQL / SQL Server collect richer engine counters when connected.

## Plugins (local marketplace)

1. Open **Plugins** (View → Plugins, or Ctrl+6)
2. Review built-in plugins (`migration`, `data_comparison`) and any user installs
3. **Enable** / **Disable** — persisted in SecureStore (`settings.plugins.enabled`)
4. **Install from Path…** — select a directory that contains `plugin.json` (see `examples/plugins/hello_echo/`), or a parent folder such as `db_storage_manager/premium_plugins/` whose subfolders each contain `plugin.json`. A parent installs every eligible child. One licence key is not reused across that parent; each premium plugin asks for its own key. **Install bundled…** registers the free plugins shipped with the app and offers the premium plugins in the same package. Built-in `migration` and `data_comparison` stay free and are already registered
5. **Install from URL…** — http(s) URL to a `.zip` or `.tar.gz` archive with the same layout
6. **Uninstall** — removes user-installed plugins only (built-ins can only be disabled)
7. **Premium plugins** — the **License** column shows `Free`, `Licensed`, `Licensed (offline)`, `Not activated`, `Expired`, `Invalid` or `Wrong product`. Select a premium plugin and use **Get License** (opens its LicenseChain checkout), then **Activate License…** and paste the key (an email prompt appears only if the purchase needs it). **Deactivate License** removes the key from this computer. Installing a premium plugin from path or URL asks for the key first, before any of its code runs
8. **Run…** — runs the selected plugin against a saved connection. `migration` copies user tables to another database of the same engine (SQLite, PostgreSQL or MySQL) and does not replace rows that are already there unless you type the target database name (the file name, for SQLite), the same confirmation a restore uses. `data_comparison` reads one table on two connections. The other premium plugins, except multi-cloud discovery, use this same dialog; multi-cloud discovery stays on Connections → **Discover Cloud…**. A missing licence, plan or role is shown as `not_available`. Passphrases are not written into the result
9. **Support DSM** — opens https://github.com/sponsors/VoxHash. Donations are optional and keep the free core and built-in plugins maintained

Premium pricing (single plugin / all-plugins bundle): US$1.99 / US$4.99 per month, US$16 / US$39 per year, or US$24 / US$59 one-time for the current major version. Updates are included while a subscription is active, or for the major version of a one-time licence. An all-plugins bundle licence unlocks every first-party premium plugin. PITR Verify is the one on sale now; the others stay listed until they ship. Discount requests: contact@voxhash.dev.

Settings → General has **Reduce transparency**, which swaps the glass surfaces for solid colours (also `DSM_REDUCE_TRANSPARENCY=1`).

Authoring API: `db_storage_manager.plugins.sdk` (API version `1.0`): opt-in, real catalogs or provider APIs, no bundled credentials. A check the plugin cannot answer is `not_available` (`plugins.sdk.not_available()`), not a guessed pass or fail. Registry on disk: `plugins/registry.json` under the user data directory. There is no remote store catalog; publish by shipping the same `plugin.json` package.

## SSH tunneling

SSH helpers live in `db_storage_manager.ssh` (`SSHTunnel`, `TunnelManager`) using Paramiko local port forwarding.

In the **Connections** tab:

1. Edit a connection and enable **Use SSH tunnel via bastion**.
2. Fill bastion host, SSH port (default 22), username, and either a private key path and/or password (password also works as a key passphrase).
3. Set **Remote Host** / **Remote Port** to the database address *as seen from the bastion* (often `localhost` and the engine port).
4. Save — settings are encrypted with the connection profile (`connections.enc`); bastion metadata is also indexed in `ssh-keys.enc` (passwords stay only in the connection profile).
5. Select the connection and click **Open Tunnel**. Status shows the local `127.0.0.1:<port>` endpoint. **Test Connection** opens the tunnel automatically when SSH is enabled.
6. **Close Tunnel** (or quit the app) tears the forwarder down.
