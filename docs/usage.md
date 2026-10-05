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

Options typically include compression and optional encryption. Scheduled backups are stored in `scheduled-backups.json`.

## Themes and language

Use **Settings** to switch theme and language. Theme application goes through `themes.manager` and `gui.utils.apply_theme_to_app`.

## SSH tunneling

SSH helpers live in `db_storage_manager.ssh` (`SSHTunnel`, `TunnelManager`) using Paramiko. Configure tunnel details on a connection when remote access requires it.
