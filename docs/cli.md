# CLI

## Desktop entry point

After `pip install -e .` (or a wheel install):

```bash
db-storage-manager
```

Equivalent module form:

```bash
python -m db_storage_manager.main
```

Both call `db_storage_manager.main:main`, which starts a PyQt6 `QApplication`, initializes i18n/theme managers, and shows `MainWindow`.

## RBAC bootstrap (shared workstation)

Create the first local admin (writes encrypted `users.enc`):

```bash
db-storage-manager-bootstrap --username admin --password '…'
# or
python -m db_storage_manager.security.bootstrap --username admin
# password via prompt, or DSM_BOOTSTRAP_USERNAME / DSM_BOOTSTRAP_PASSWORD
```

After bootstrap, start the desktop app and sign in. Manage additional users under **Settings → Users & RBAC**.

## REST + Web UI companion

Desktop remains primary. The companion exposes a local HTTP API and a small glance UI over the same SecureStore / local backups the desktop app uses.

```bash
db-storage-manager-api
# or
python -m db_storage_manager.api
# or (loads gitignored .env.api.local from the repo)
./scripts/run-api-local.sh
```

Defaults: `http://127.0.0.1:8765/` (Web UI) and `/api/v1/*`.

| Flag / env | Meaning |
|---|---|
| `--host` / `DSM_API_HOST` | Bind host (default `127.0.0.1`) |
| `--port` / `DSM_API_PORT` | Bind port (default `8765`) |
| `--token` / `DSM_API_TOKEN` | If set, require `Authorization: Bearer …` (except `/api/v1/health`); with RBAC active, Bearer maps to system admin |
| `--backup-dir` | Override local backup directory |

When RBAC accounts exist, unauthenticated API calls (except health/static) return **401**. Prefer HTTP Basic with a local user, or Bearer `DSM_API_TOKEN`. Missing permissions return **403**.

### Local token file (recommended)

Keep the Bearer token out of shell history and git:

```bash
cp .env.api.local.example .env.api.local
# or generate a fresh token file (mode 600, gitignored via .env.*.local):
./scripts/setup-api-token.sh
./scripts/run-api-local.sh
```

`.env.api.local` sets `DSM_API_HOST`, `DSM_API_PORT`, and `DSM_API_TOKEN`. Never commit that file.

Example without a file:

```bash
export DSM_API_TOKEN="$(openssl rand -hex 32)"
db-storage-manager-api --port 8765
curl -s http://127.0.0.1:8765/api/v1/health
curl -s -H "Authorization: Bearer $DSM_API_TOKEN" http://127.0.0.1:8765/api/v1/connections
```

## Desktop behavior

- The GUI launcher is **not** a multi-subcommand CLI.
- Closing the main window exits the process (`sys.exit(app.exec())`).

## Headless smoke check

```bash
QT_QPA_PLATFORM=offscreen python -c "
from PyQt6.QtWidgets import QApplication
import sys
from db_storage_manager.gui.main_window import MainWindow
app = QApplication(sys.argv)
print(MainWindow().windowTitle())
"
```

## Exit codes

- Normal GUI shutdown follows Qt’s event loop exit code.
- Companion shutdown is via Ctrl+C / process signal.
- Import or dependency failures exit non-zero before the window or server appears.
