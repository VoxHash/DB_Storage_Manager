# Quick Start

End-to-end path from a clean machine to a running desktop app.

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
db-storage-manager
```

Verify the package without opening a window:

```bash
python -c "from db_storage_manager import __version__; print(__version__)"
QT_QPA_PLATFORM=offscreen python -c "
from PyQt6.QtWidgets import QApplication
import sys
from db_storage_manager.gui.main_window import MainWindow
app = QApplication(sys.argv)
w = MainWindow()
print(w.windowTitle())
"
```

Expected: version `1.0.2` and window title `DB Storage Manager`.

If `pip install -r requirements.txt` fails on an optional engine (historically `cx_Oracle`), install core requirements only and add engines via extras — see [installation.md](installation.md).
