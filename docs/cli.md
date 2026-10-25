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

## REST + Web UI companion

Desktop remains primary. The companion exposes a local HTTP API and a small glance UI over the same SecureStore / local backups the desktop app uses.

```bash
db-storage-manager-api
# or
python -m db_storage_manager.api
```

Defaults: `http://127.0.0.1:8765/` (Web UI) and `/api/v1/*`.

| Flag / env | Meaning |
|---|---|
| `--host` / `DSM_API_HOST` | Bind host (default `127.0.0.1`) |
| `--port` / `DSM_API_PORT` | Bind port (default `8765`) |
| `--token` / `DSM_API_TOKEN` | If set, require `Authorization: Bearer …` (except `/api/v1/health`) |
| `--backup-dir` | Override local backup directory |

Example:

```bash
export DSM_API_TOKEN="$(openssl rand -hex 16)"
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
