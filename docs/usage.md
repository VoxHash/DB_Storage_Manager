# Usage

## Connections

1. Open **Connections**
2. Add a profile with type, name, and credentials (or SQLite path)
3. **Test Connection** before saving
4. Credentials are written to `connections.enc` through `SecureStore`

Supported types in the UI factory: `postgresql`, `mysql`/`mariadb`, `sqlite`, `mongodb`, `redis`, `oracle`, `sqlserver`/`mssql`, `clickhouse`, `influxdb`.

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

- **Local** — files under the user data `backups/` directory
- **S3** — requires AWS credentials and bucket configuration
- **Google Drive** — requires Google API credentials
- **Proton Drive** — uploads via rclone `protondrive` remote (credentials from `.env.protondrive.local` / SecureStore / env; never commit secrets)

On the **Backups** tab:

1. **Create Backup** — pick a connection, adapter (Local or Proton Drive), compression, and encryption passphrase (required for Proton Drive when encryption is on; preferred for opsec).
2. **Restore** — **Refresh** lists local backups; **Refresh Proton Drive** lists remote objects when rclone + account are configured.
3. **Verify Checksum** / **Dry-run Restore** work on local rows; for Proton Drive rows the app downloads to a temp file, verifies SHA-256 against the `.meta.json` sidecar, then cleans up.

Proton Drive is not configured until rclone is installed and either an rclone remote exists or `DSM_PROTONDRIVE_USERNAME` + `DSM_PROTONDRIVE_PASSWORD` are set — the UI shows a clear status line instead of a fake local path. Scheduled backups are stored in `scheduled-backups.json`.

## Themes and language

Use **Settings** to switch theme and language. Theme application goes through `themes.manager` and `gui.utils.apply_theme_to_app`.

## Monitoring and alerts

1. Open **Monitoring**
2. Select a saved connection and click **Start Monitoring**
3. The status banner shows overall health and active alert counts (critical / warning / info)
4. **Metrics**, **Alerts**, **Performance**, and **Health** tabs refresh every 5 seconds from the real `monitoring/` collectors (not placeholders)
5. On **Alerts**, select rows and **Acknowledge Selected**, or **Acknowledge All**; **Refresh Now** forces an immediate poll

Thresholds (connection count, cache hit ratio, health failures) live in `AlertManager`. SQLite reports basic connectivity metrics; PostgreSQL / MySQL / SQL Server collect richer engine counters when connected.

## Plugins (local marketplace)

1. Open **Plugins** (View → Plugins, or Ctrl+6)
2. Review built-in plugins (`migration`, `data_comparison`) and any user installs
3. **Enable** / **Disable** — persisted in SecureStore (`settings.plugins.enabled`)
4. **Install from Path…** — select a directory that contains `plugin.json` (see `examples/plugins/hello_echo/`)
5. **Install from URL…** — http(s) URL to a `.zip` or `.tar.gz` archive with the same layout
6. **Uninstall** — removes user-installed plugins only (built-ins can only be disabled)

Authoring API: `db_storage_manager.plugins.sdk` (API version `1.0`). Registry on disk: `plugins/registry.json` under the user data directory. There is no remote store catalog yet; publish later by shipping the same `plugin.json` package.

## SSH tunneling

SSH helpers live in `db_storage_manager.ssh` (`SSHTunnel`, `TunnelManager`) using Paramiko local port forwarding.

In the **Connections** tab:

1. Edit a connection and enable **Use SSH tunnel via bastion**.
2. Fill bastion host, SSH port (default 22), username, and either a private key path and/or password (password also works as a key passphrase).
3. Set **Remote Host** / **Remote Port** to the database address *as seen from the bastion* (often `localhost` and the engine port).
4. Save — settings are encrypted with the connection profile (`connections.enc`); bastion metadata is also indexed in `ssh-keys.enc` (passwords stay only in the connection profile).
5. Select the connection and click **Open Tunnel**. Status shows the local `127.0.0.1:<port>` endpoint. **Test Connection** opens the tunnel automatically when SSH is enabled.
6. **Close Tunnel** (or quit the app) tears the forwarder down.
