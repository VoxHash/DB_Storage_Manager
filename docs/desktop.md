# Desktop install and use (Linux / macOS / Windows)

The **production client** today is the PyQt6 desktop app (`db-storage-manager`). Android / GrapheneOS and Meta Quest companions are exploratory (see [android-grapheneos.md](android-grapheneos.md), [quest.md](quest.md), [cross-platform.md](cross-platform.md)).

## Prerequisites

- Python **3.10–3.12** (3.12 recommended)
- A graphical desktop session (or `QT_QPA_PLATFORM=offscreen` for smoke tests only)
- Git

Optional:

- Host ODBC Instant Client packages only if you use SQL Server / Oracle Thick mode — see [installation.md](installation.md)
- `rclone` with a `protondrive` remote for Proton Drive backups
- Cloud vendor CLIs (`aws`, `gcloud`, `az`) for **Discover Cloud…** via default credential chains

## Install (project `.venv`)

Prefer a **single** project virtualenv. Avoid `pip install --user`.

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e ".[engines]"        # or: pip install -e .
# Optional cloud discovery SDKs:
pip install -e ".[cloud]"
```

Optional `~/.local/bin` shims that point only at this repo’s `.venv`:

```bash
./scripts/install-local-shims.sh
which -a db-storage-manager db-storage-manager-api
```

### Native wheels (optional)

Prebuilt `db_storage_native` wheels ship on GitHub Releases (Linux x86_64, Windows x64, macOS arm64). Download the matching wheel, then:

```bash
pip install ./db_storage_native-*.whl
python -c "from db_storage_manager.native import backend_info; print(backend_info())"
```

Local Rust builds: `pip install -e ".[native]"` then `maturin develop --release` under `native/db_storage_native`. Pure-Python fallbacks always work without the wheel.

## Launch

```bash
db-storage-manager
# or
python -m db_storage_manager.main
```

When RBAC accounts exist (`users.enc`), a **Sign in** dialog appears before the main window.

## First workflows

1. **Connections** — add / test / save encrypted profiles; optional SSH bastion; optional **Discover Cloud…**
2. **Dashboard** — storage analysis for the selected connection
3. **Query Console** — keep Safe Mode on for production
4. **Backups** — local, S3, Google Drive, or Proton Drive; prefer DSMENC1 encryption before cloud upload
5. **Monitoring / Plugins / Settings** — as needed

Details: [usage.md](usage.md), [getting-started.md](getting-started.md).

## Multi-user / RBAC

Bootstrap the first admin (writes encrypted `users.enc`):

```bash
db-storage-manager-bootstrap --username admin --password '…'
# or
python -m db_storage_manager.security.bootstrap --username admin
```

Manage users under **Settings → Users & RBAC**. Keep bootstrap credentials only in gitignored `.env.rbac.local` (mode `600`); see `.env.rbac.local.example` and [cli.md](cli.md).

## Cloud discovery (RDS / Cloud SQL / Azure SQL)

```bash
pip install -e ".[cloud]"
./scripts/setup-cloud-env.sh   # writes gitignored .env.cloud.local (mode 600)
```

Authenticate with vendor default chains (preferred over pasting long-lived keys into the env file):

```bash
aws configure                                 # or SSO / instance role
gcloud auth application-default login         # then set DSM_GCP_PROJECT_ID
az login && az account set --subscription …   # then set DSM_AZURE_SUBSCRIPTION_ID
```

In the app: **Connections → Discover Cloud… → Refresh Discovery → Import Selected**. See [configuration.md](configuration.md) and `.env.cloud.local.example`.

Optional live pytest (local only, never in CI without your intent):

```bash
DSM_LIVE_CLOUD=1 pytest tests/test_cloud_managed.py -k live -v
```

## Proton Drive backups

1. Install [rclone](https://rclone.org/install/) with the `protondrive` backend.
2. `rclone config` **or** copy `.env.protondrive.local.example` → `.env.protondrive.local` (gitignored, mode `600`).
3. Backups tab → destination **Proton Drive**; prefer encryption on.

## REST / Web companion (same machine)

Desktop remains primary. For a local glance UI / API over the same SecureStore:

```bash
./scripts/setup-api-token.sh
./scripts/run-api-local.sh
# → http://127.0.0.1:8765/
```

Defaults bind **localhost only**. See [cli.md](cli.md) and [cross-platform.md](cross-platform.md) for token / RBAC / LAN opsec.

## Opsec checklist

| Item | Practice |
|---|---|
| Secrets | `.env`, `.env.*.local`, `connections.enc`, `.master-key` — gitignored; never commit |
| File mode | `chmod 600` on local env files and the master key |
| Encryption | Fernet for stored profiles; DSMENC1 for backup payloads when enabled |
| RBAC | Enable on shared workstations; least-privilege roles |
| API token | `DSM_API_TOKEN` in `.env.api.local`; require Bearer (or Basic when RBAC is on) |
| Cloud keys | Prefer `aws` / `gcloud` / `az` default chains over static keys in `.env.cloud.local` |
| Safe Mode | Leave on unless you intentionally need writes |

## Platform notes

- **Linux**: Qt platform plugins via PyQt6 wheels; Arch/Garuda ODBC helper: `./scripts/setup-host-odbc-arch.sh`
- **macOS**: same `.venv` flow; native wheel is arm64
- **Windows**: activate with `.venv\Scripts\activate`; user data under `%APPDATA%\DB Storage Manager\`

Full platform install matrix: [installation.md](installation.md).
