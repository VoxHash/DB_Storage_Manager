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
| `ssh-keys.enc` | Encrypted SSH bastion metadata index (host/user/key path per connection; passwords stay in `connections.enc`) |
| `scheduled-backups.json` | Backup schedule definitions |
| `backups/` | Local backup payloads |
| `plugins/registry.json` | Local plugin marketplace registry (builtins + installs) |
| `plugins/installed/` | Copied user-installed plugin packages |
| `users.enc` | Encrypted local RBAC accounts (password hashes; mode `600`) |
| `.master-key` | Fernet master key (Unix mode `600`) |

Plugin enable/disable flags are stored under the encrypted settings key `plugins.enabled` (not in `registry.json`).

### Multi-user / RBAC

When `users.enc` contains at least one account, RBAC is active: desktop login is required, and permissions gate connections, backups, settings, plugins, and companion API routes. Bootstrap:

```bash
db-storage-manager-bootstrap --username admin --password '…'
```

Settings key `rbac.enabled` mirrors whether accounts exist (informational). Roles: `admin`, `user`, `viewer`, `guest`.

## Environment variables

No required secrets for core operation. Useful optional variables:

| Variable | Purpose |
|---|---|
| `QT_QPA_PLATFORM=offscreen` | Headless GUI smoke tests |
| `APPDATA` | Windows user data root (OS-provided) |
| `ORACLE_CLIENT_LIB_DIR` | Optional path to Oracle Instant Client libraries (enables `oracledb` Thick mode) |
| `DSM_E2E_CONNECTIONS_FILE` | Absolute path to a local JSON fixture of real DB profiles for optional live probes (`tests/test_real_connections.py`) |
| `DSM_E2E_CONNECT_TIMEOUT` | Seconds for each live `test_connection()` probe (default `8`) |
| AWS / Google credentials | S3 / Google Drive backup adapters, and optional RDS / Cloud SQL discovery |
| `DSM_AWS_REGION` / `DSM_AWS_ACCESS_KEY_ID` / `DSM_AWS_SECRET_ACCESS_KEY` / `DSM_AWS_PROFILE` | AWS RDS discovery + IAM auth tokens (or use the default AWS credential chain) |
| `DSM_AWS_RDS_SSL_CA` | Path to the RDS CA bundle for `sslmode=verify-full` / IAM TLS |
| `DSM_GCP_PROJECT_ID` / `DSM_GCP_CREDENTIALS` | GCP Cloud SQL discovery (`GOOGLE_CLOUD_PROJECT` / `GOOGLE_APPLICATION_CREDENTIALS` also accepted) |
| `DSM_AZURE_SUBSCRIPTION_ID` / `DSM_AZURE_TENANT_ID` / `DSM_AZURE_CLIENT_ID` / `DSM_AZURE_CLIENT_SECRET` | Azure SQL discovery + Entra tokens (or `DefaultAzureCredential` / `az login`) |
| `DSM_PROTONDRIVE_USERNAME` / `DSM_PROTONDRIVE_PASSWORD` | Proton Drive account for rclone-backed cloud backups (or use an existing rclone `protondrive` remote) |
| `DSM_PROTONDRIVE_REMOTE` | rclone remote name (default `protondrive`) |
| `DSM_PROTONDRIVE_PATH` | Folder on Proton Drive (default `db-storage-manager-backups`) |
| `DSM_PROTONDRIVE_RCLONE` | rclone binary path (default `rclone` on `PATH`) |
| `DSM_PROTONDRIVE_OTP_SECRET` / `DSM_PROTONDRIVE_2FA` | Optional TOTP secret or one-shot 2FA code |
| `RCLONE_PROTONDRIVE_*` | Alternate env names accepted by rclone itself |
| LDAP / MFA related settings | Only when auth features are enabled |

Database passwords belong in the encrypted connection store, not in `.env` files committed to git. `.env`, `.env.*.local` (including `.env.protondrive.local`, `.env.cloud.local`, `.env.rbac.local`, `.env.api.local`, `.env.e2e.local`), and `tests/fixtures/connections.local.json` are gitignored. Ship only `*.example` templates (empty password placeholders).

### Cloud-managed databases (RDS / Cloud SQL / Azure SQL)

1. Optional extras: `pip install -e ".[aws]"`, `".[gcp]"`, `".[azure]"`, or `".[cloud]"` (boto3 is already a core dependency; Azure/GCP Admin SDKs are optional).
2. Copy `.env.cloud.local.example` → `.env.cloud.local` (gitignored) or set the `DSM_*` / cloud vendor env vars above. Non-secret defaults can also live under SecureStore settings key `cloud_managed`.
3. In **Connections**, use **Discover Cloud…** → **Refresh Discovery** → select instances → **Import Selected** (password later, or IAM / Entra token mode).
4. Imported profiles store `extra.cloud_provider` / `extra.auth_mode` / SSL hints. RDS IAM uses `generate_db_auth_token` at connect time; Azure Entra uses ODBC access tokens; Cloud SQL IAM DB auth needs the Auth Proxy or `cloud-sql-python-connector`.
5. Live cloud API calls are skipped in CI unless you set credentials locally (`DSM_LIVE_CLOUD=1` for the optional live pytest).

### Proton Drive backups

1. Install [rclone](https://rclone.org/install/) with the `protondrive` backend.
2. Log into Proton Drive once in a browser so account keys exist (rclone requirement).
3. Either run `rclone config` and create a `protondrive` remote, **or** copy `.env.protondrive.local.example` → `.env.protondrive.local` and set username/password (optional OTP secret).
4. Non-secret defaults (`remote`, `path`, `prefer_encryption`) can also live under SecureStore settings key `proton_drive`.
5. Prefer encryption on: payloads are DSMENC1-encrypted and checksummed locally before upload.

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
