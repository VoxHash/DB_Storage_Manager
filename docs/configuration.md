# Configuration

## Application settings (GUI)

Open the **Settings** tab. Defaults from `db_storage_manager.config.DEFAULT_SETTINGS`:

| Setting | Description | Default |
|---|---|---|
| `theme` | UI theme (`light`, `dark`, `dracula`) | `dark` |
| `language` | i18n language code | `en` |
| `safe_mode` | Block non-SELECT queries by default | `True` |
| `auto_connect` | Connect on startup | `False` |
| `notifications` | Desktop notifications | `True` |
| `telemetry` | Anonymous telemetry | `False` |

Settings are persisted encrypted via `SecureStore.set_settings()` / `get_settings()`.

## User data paths

| Platform | Directory |
|---|---|
| Linux / macOS | `~/.config/db-storage-manager/` |
| Windows | `%APPDATA%\DB Storage Manager\` |

Key files:

| File | Purpose |
|---|---|
| `connections.enc` | Encrypted connection profiles |
| `settings.enc` | Encrypted app settings |
| `ssh-keys.enc` | Encrypted SSH key material |
| `scheduled-backups.json` | Backup schedule definitions |
| `backups/` | Local backup payloads |
| `.master-key` | Fernet master key (Unix mode `600`) |

## Environment variables

No required secrets for core operation. Useful optional variables:

| Variable | Purpose |
|---|---|
| `QT_QPA_PLATFORM=offscreen` | Headless GUI smoke tests |
| `APPDATA` | Windows user data root (OS-provided) |
| AWS / Google credentials | Only for S3 or Google Drive backup adapters |
| LDAP / MFA related settings | Only when auth features are enabled |

Database passwords belong in the encrypted connection store, not in `.env` files committed to git. `.env` is gitignored if you use local dotenv files for personal automation.

## Default ports

Defined in `DEFAULT_PORT`:

| Engine | Port |
|---|---|
| PostgreSQL | 5432 |
| MySQL / MariaDB | 3306 |
| MongoDB | 27017 |
| Redis | 6379 |
| Oracle | 1521 |
| SQL Server | 1433 |
| ClickHouse | 9000 |
| InfluxDB | 8086 |
| SQLite | n/a (file path) |

## Connection timeout

`DEFAULT_TIMEOUT = 30` seconds for connection attempts.
