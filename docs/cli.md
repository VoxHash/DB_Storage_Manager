# CLI

## Entry point

After `pip install -e .` (or a wheel install):

```bash
db-storage-manager
```

Equivalent module form:

```bash
python -m db_storage_manager.main
```

Both call `db_storage_manager.main:main`, which starts a PyQt6 `QApplication`, initializes i18n/theme managers, and shows `MainWindow`.

## Behavior

- This is a **desktop GUI** launcher, not a multi-subcommand CLI.
- There are no positional arguments or `--help` subcommands beyond what the console script provides by packaging metadata.
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
- Import or dependency failures exit non-zero before the window appears.
