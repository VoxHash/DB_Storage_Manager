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
| `notification_timeout_seconds` | Seconds before a desktop notification auto-dismisses (clamped 2-60; some desktops treat it as a hint) | `5` |
| `update_channel` | Channel used by Settings → Updates: `stable` or `experimental` (GitHub pre-releases) | `stable` |
| `update_auto_check` | When true, ask the public GitHub Releases API at most once every 24 hours. Nothing is installed | `false` |
| `retention` | `enabled`, `keep_daily`, `keep_monthly`, and optional `connections` overrides. Off deletes nothing. Prunes Local, Proton Drive and S3 after a scheduled backup | off, 7 daily, 6 monthly |
| `telemetry` | Anonymous telemetry | `False` |
| `experimental.restore` | Shows **Restore…**. Uncheck to hide it. A missing key is on. `DSM_EXPERIMENTAL=1` forces it on | `True` |
| `discord_alerts` | Discord webhook `url`, `min_severity`, `cooldown_minutes`. Secret stays in SecureStore. Off until Monitoring enables Discord | empty URL |
| `telegram_alerts` | `bot_token`, `chat_id`, `min_severity`, `cooldown_minutes`. Posts only to `api.telegram.org`. Off until Monitoring enables Telegram | empty |
| `connection_email_alerts` | Per-connection SMTP for `connection-email-alerts`. Passwords stay here | `connections` empty |
| `multi_connection_monitor` | Connection ids and `min_interval_seconds` for `multi-connection-monitor`. An empty list does not poll | `[]`, 60 seconds |
| `email_alerts` | SMTP alert channel: `host`, `port`, `security` (`starttls` / `ssl` / `none`), `username`, `sender`, `recipients`, `min_severity` (`warning` / `critical`), `cooldown_minutes`. The password is stored encrypted | host empty (channel unavailable) |
| `monitoring.autostart_connection_id` | Connection watched automatically when the app opens (checkbox in Monitoring) | `None` |
| `s3_backup` | `bucket`, `prefix`, `region`, `endpoint` (MinIO / R2 / B2) and optional access keys, stored encrypted | empty |

The **Settings** tab is split into **General**, **Backups & Adapters**, **Notifications**, **Users & RBAC** and **Updates**. Saving only changes the keys it shows, so values written by other tabs (S3, Proton Drive, alert channels) are preserved.

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
| `scheduled-backups.json` | Backup schedule definitions (no secrets) |
| `scheduled-backup-secrets.enc` | Encrypted passphrases for scheduled backups, keyed by schedule id (mode `600`) |
| `backups/` | Local backup payloads |
| `plugins/registry.json` | Local plugin marketplace registry (builtins + installs) |
| `plugins/installed/` | Copied user-installed plugin packages |
| `plugin-licenses.enc` | Fernet-encrypted premium plugin licence records (key, email, last verification); the key is never logged |
| `users.enc` | Encrypted local RBAC accounts (password hashes; mode `600`) |
| `.master-key` | Fernet master key (Unix mode `600`) |

Plugin enable/disable flags are stored under the encrypted settings key `plugins.enabled` (not in `registry.json`).

### Multi-user / RBAC

When `users.enc` contains at least one account, RBAC is active: desktop login is required, and permissions gate connections, backups, settings, plugins, and companion API routes. Bootstrap:

```bash
db-storage-manager-bootstrap --username admin --password '…'
```

Settings key `rbac.enabled` mirrors whether accounts exist (informational). Roles: `admin`, `user`, `viewer`, `guest`, `monitor`. The `monitor` role is for on-call users: it can read dashboards, connections, backups, settings and plugins and may start monitoring, edit thresholds, channels and acknowledge alerts (`monitoring:read` / `monitoring:write`), but cannot create backups, restore, run queries or change connections.

Permission matrix (`db_storage_manager.security.auth.ROLE_PERMISSIONS`; `admin` holds `*`). The desktop UI and the REST API enforce the same permission strings:

| Permission | admin | user | monitor | viewer | guest |
|---|:-:|:-:|:-:|:-:|:-:|
| `dashboard:read`, `connections:read`, `api:read` | yes | yes | yes | yes | yes |
| `backups:read`, `settings:read`, `plugins:read`, `monitoring:read` | yes | yes | yes | yes | no |
| `connections:write`, `connections:delete` | yes | yes | no | no | no |
| `backups:create`, `backups:restore` | yes | yes | no | no | no |
| `query:execute` (SELECT console) | yes | yes | no | no | no |
| `query:write` (non-SELECT, Safe Mode off) | yes | yes | no | no | no |
| `monitoring:write` (thresholds, channels, acknowledge) | yes | yes | yes | no | no |
| `api:write` | yes | yes | no | no | no |
| `settings:write`, `plugins:manage`, `users:manage` | yes | no | no | no | no |

There is no separate `backups:delete`. Removing a backup in the UI uses `backups:create`. Retention pruning is not an interactive action: it follows a policy an admin saved (`settings:write`) and runs after a scheduled backup, including when nobody is signed in. A monitor cannot turn pruning on and cannot restore. Changing a username or email needs `users:manage` (admin). Guest can list connection names; passwords stay in SecureStore and are not part of the public user record.

Failed sign-ins are throttled: after 5 failures within 60 seconds the username is locked out for the rest of that window (desktop sign-in dialog and API Basic auth).

TOTP (authenticator app) is optional per user. Settings → Users & RBAC → **Authenticator…** shows a QR code of the `otpauth://` URI, the same URI as text, and the manual key. MFA is enabled only after a valid code. Until that code is accepted, password login still works; dismissing the dialog drops the pending secret. The sign-in dialog accepts the 6-digit code with or without spaces. The companion API sends the same code in the `X-DSM-MFA` header next to HTTP Basic; a password alone is rejected once MFA is on. There is no WebAuthn ceremony in this app. **Edit account…** changes username and email for an admin; the password hash and authenticator secret stay on that record.

`.env.rbac.local` is a gitignored, mode `600` local file. It uses the keys `USERNAME` and `PASSWORD` (template: `.env.rbac.local.example`) and is read by the opt-in sign-in tests in `tests/test_gui_shell.py`. The application itself does not read it; to create the first admin use `db-storage-manager-bootstrap` (flags, or `DSM_BOOTSTRAP_USERNAME` / `DSM_BOOTSTRAP_PASSWORD`). Never commit it.

## Environment variables

No required secrets for core operation. Useful optional variables:

| Variable | Purpose |
|---|---|
| `QT_QPA_PLATFORM=offscreen` | Headless GUI smoke tests |
| `APPDATA` | Windows user data root (OS-provided) |
| `ORACLE_CLIENT_LIB_DIR` | Optional path to Oracle Instant Client libraries (enables `oracledb` Thick mode) |
| `DSM_E2E_CONNECTIONS_FILE` | Absolute path to a local JSON fixture of real DB profiles for optional live probes (`tests/test_real_connections.py`) |
| `DSM_REDUCE_TRANSPARENCY` | `1` flattens glass surfaces to solid colours (also a Settings checkbox) |
| `LICENSECHAIN_API_BASE` | LicenseChain API base for premium plugin licences (default `https://api.licensechain.app/v1`; must be `https` except for localhost) |
| `LICENSECHAIN_PAY_BASE` | LicenseChain hosted checkout / validate base (default `https://pay.licensechain.app`) |
| `LICENSECHAIN_API_KEY` | Only for `scripts/licensechain_products.py --apply` (maintainers creating products). Never needed by users and never stored by the app |
| `DSM_LICENSE_RECHECK_HOURS` | Hours between online licence re-checks (default `24`) |
| `DSM_LICENSE_GRACE_DAYS` | Days a verified licence keeps working offline (default `7`) |
| `DSM_LICENSECHAIN_HWUID` | `0` disables sending the hashed device id with licence verification (default on) |
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
| `DSM_EXPERIMENTAL` | `1` / `true` / `yes` / `on` forces full restore on even when `experimental.restore` is false |
| `DSM_S3_BUCKET` / `DSM_S3_PREFIX` / `DSM_S3_REGION` / `DSM_S3_ENDPOINT` | S3-compatible backup destination (override SecureStore `s3_backup`) |
| `DSM_S3_ACCESS_KEY_ID` / `DSM_S3_SECRET_ACCESS_KEY` | S3 credentials; otherwise `AWS_*` variables or the default boto3 chain (profile, instance role) |
| `DSM_SMTP_HOST` / `DSM_SMTP_PORT` / `DSM_SMTP_SECURITY` / `DSM_SMTP_USERNAME` / `DSM_SMTP_PASSWORD` / `DSM_SMTP_FROM` / `DSM_SMTP_TO` | SMTP alert channel (override SecureStore `email_alerts`; `DSM_SMTP_TO` is a comma-separated list) |
| `DSM_DISCORD_WEBHOOK_URL` | Discord incoming webhook (override SecureStore `discord_alerts.url`) |
| `DSM_TELEGRAM_BOT_TOKEN` / `DSM_TELEGRAM_CHAT_ID` | Telegram bot token and chat id (override SecureStore `telegram_alerts`). There is no URL override; posts go to `api.telegram.org` only |
| `X-DSM-MFA` | TOTP code for companion API Basic auth when that user has an authenticator enabled |

Database passwords belong in the encrypted connection store, not in `.env` files committed to git. `.env`, `.env.*.local` (including `.env.protondrive.local`, `.env.cloud.local`, `.env.rbac.local`, `.env.api.local`), and `tests/fixtures/connections.local.json` are gitignored. Ship only `*.example` templates (empty password placeholders).

`.env.cloud.local.example` and `.env.protondrive.local.example` stay separate files. Cloud discovery and Proton Drive are different credential domains, loaded by different helpers (`load_cloud_dotenv` / `load_protondrive_dotenv`) into different gitignored files, and each has its own setup script. One combined example would invite an AWS key and a Proton password into the same file.

Live sibling-database probes do not read an env file. `tests/test_real_connections.py` uses `tests/fixtures/connections.local.json` (gitignored) and the process environment `DSM_E2E_CONNECTIONS_FILE` / `DSM_E2E_CONNECT_TIMEOUT`. There is no `.env.e2e.local.example`.

### Importing connections

| Source | How | Notes |
|---|---|---|
| Project `.env` | Connections → **Import from .env…** or `POST /api/v1/connections/import/env` | Parses `DATABASE_URL`, `DIRECT_URL`, `DATABASE_URL_UNPOOLED`, `DB_*`, `POSTGRES_*`, `MYSQL_*`. Prefers direct/unpooled URLs first. |
| SSH key folder | Connections → **Import SSH key…** or `POST /api/v1/connections/import/ssh` | Reads private `KEY` (path referenced, not copied to git). Optional `SSH.pub`, `VPS.txt` (bastion host/user), `DB.txt` (database/user/password). Builds an SSH-tunnel MySQL/Postgres profile. |
| OAuth / grant permissions | Not fully automated | Platforms need a registered OAuth client + user tokens. See `db_storage_manager.importers.oauth_platforms` and `GET /api/v1/connections/import/platforms`. Until then, export `.env` from the dashboard or use SSH import. |

Local e2e helper (never commits secrets):

```bash
.venv/bin/python scripts/import_connections_e2e.py --save-on-pass \
  --json-out artifacts/import-dumps/report.local.json
```

Optional pytest live probes: `DSM_E2E_IMPORT=1 pytest -v tests/test_import_connections_e2e.py`.

### Cloud-managed databases (RDS / Cloud SQL / Azure SQL)

1. Optional extras: `pip install -e ".[aws]"`, `".[gcp]"`, `".[azure]"`, or `".[cloud]"` (boto3 is already a core dependency; Azure/GCP Admin SDKs are optional — GCP uses PyPI `google-cloud-sql`).
2. Prefer `./scripts/setup-cloud-env.sh` (writes gitignored `.env.cloud.local`, mode `600`, default credential chains — no invented static keys) or copy `.env.cloud.local.example`. Authenticate with `aws configure`, `gcloud auth application-default login`, and/or `az login`. Non-secret defaults can also live under SecureStore settings key `cloud_managed`.
3. In **Connections**, use **Discover Cloud…** → **Refresh Discovery** → select instances → **Import Selected** (password later, or IAM / Entra token mode).
4. Imported profiles store `extra.cloud_provider` / `extra.auth_mode` / SSL hints. RDS IAM uses `generate_db_auth_token` at connect time; Azure Entra uses ODBC access tokens; Cloud SQL IAM DB auth needs the Auth Proxy or `cloud-sql-python-connector`.
5. Live cloud API calls are skipped in CI unless you set credentials locally (`DSM_LIVE_CLOUD=1` for the optional live pytest).
6. Desktop / companion opsec: [desktop.md](desktop.md), [cross-platform.md](cross-platform.md).

### Proton Drive backups

1. Install [rclone](https://rclone.org/install/) with the `protondrive` backend (user-local `~/.local/bin/rclone` is resolved even when desktop launchers omit that directory from `PATH`).
2. Log into Proton Drive once in a browser so account keys exist (rclone requirement).
3. Configure credentials (pick one — never commit secrets):
   - **In-app (preferred):** Settings → **Configure Proton Drive…** or Backups → Adapter **Proton Drive** → **Configure Proton Drive…** — username / password / optional OTP are stored encrypted in SecureStore (`proton_drive`).
   - **Env file:** `./scripts/setup-protondrive-env.sh` (interactive TTY prompts, or copy `.env.protondrive.local.example` → `.env.protondrive.local` and edit). Mode `600`, gitignored. The app loads this file automatically.
   - **rclone remote:** `rclone config` and create a remote named `DSM_PROTONDRIVE_REMOTE` (default `protondrive`).
4. Non-secret defaults (`remote`, `path`, `prefer_encryption`) live under SecureStore settings key `proton_drive`.
5. Prefer encryption on: payloads are DSMENC1-encrypted and checksummed locally before upload.
6. Ready when rclone is found **and** SecureStore/env has username+password **or** the rclone remote exists — the Backups orange banner clears.

### S3-compatible backups

1. Backups → Adapter **S3** → **Configure S3…** (bucket, prefix, region, optional endpoint for MinIO / Cloudflare R2 / Backblaze B2, optional access keys) or set `DSM_S3_*`. Without explicit keys the default boto3 credential chain is used.
2. Uploads are always DSMENC1-encrypted (checkbox locked on) and checksummed before leaving the machine; objects carry a `.meta.json` sidecar.
3. Google Drive stays a library-only adapter (`GoogleDriveBackupAdapter`) and is not offered in the desktop UI: an OAuth refresh token in a desktop form is a larger opsec risk than the benefit. Use S3 / Proton Drive, or an rclone `drive` remote through a plugin (see [ROADMAP.md](../ROADMAP.md)).

### Email alerts (SMTP)

Settings → Notifications → **Email alerts**: host, port, security (`starttls`, `ssl`, or `none` for loopback relays only), user, password, sender, recipients, minimum severity and per-alert cooldown. The **Email** checkbox in Monitoring → Channels is only enabled when the SMTP configuration is complete. A failed send is logged and does not start the cooldown, so the next occurrence is mailed again.

### Full restore and the audit log

**Restore…** is available on the Backups tab. It requires the `backups:restore` permission when RBAC is active, a typed confirmation, and a safety backup. Every attempt, successful or not, is appended to `audit.log` (JSON lines, mode `600`, secrets stripped) in the user data directory. PostgreSQL drops each archived table with `CASCADE` before `pg_restore --clean`, so a foreign key from a table that exists only on the target does not block the restore.

End-to-end tests cover SQLite. Other engines use their driver's `restore_backup`. Rehearse into a scratch database when the target has objects you need to keep.

### Discord and Telegram alerts

Settings → Notifications. Discord takes an incoming webhook URL (`https://discord.com/api/webhooks/<id>/<token>`, also discordapp.com, canary, and ptb). Telegram takes a bot token and a chat id; the send URL is built at runtime as `https://api.telegram.org/bot<token>/sendMessage` and is not stored. Both follow the same minimum severity and cooldown as email. The Monitoring checkboxes stay disabled until the configuration is valid. Tokens and URLs are not written to the notification log. Nothing is bundled.

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
