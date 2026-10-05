# Installation

## Supported platforms

- Windows, macOS, Linux
- Python 3.10+ (3.10–3.12 validated in CI and local release validation)

## Standard install

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
```

Entry points after editable install:

- `python -m db_storage_manager.main`
- `db-storage-manager`

## Optional database engines

Core install covers PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, and Redis.

| Engine | Extra / pip package | System note |
|---|---|---|
| SQL Server | `pip install -e ".[mssql]"` (`pyodbc`) | ODBC driver required on the host |
| ClickHouse | `pip install -e ".[clickhouse]"` | — |
| InfluxDB | `pip install -e ".[influxdb]"` | — |
| Oracle | `pip install -e ".[oracle]"` (`cx_Oracle`) | Oracle Instant Client required; wheel builds often fail without it |
| All non-Oracle engines | `pip install -e ".[engines]"` | — |

Missing optional drivers raise a clear `ImportError` when that engine is selected (for example: `cx_Oracle is required for Oracle support`).

## System packages (Linux)

```bash
sudo apt-get update
sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtcharts
```

macOS users typically rely on the PyQt6 wheels from pip. Windows users may need the Visual C++ Redistributable if wheel installs fail.

## Development install

```bash
pip install -e ".[dev]"
pytest -v
black --check db_storage_manager/
flake8 db_storage_manager/ --count --select=E9,F63,F7,F82
```

## Release binaries

GitHub Releases may include platform executables built by `.github/workflows/release.yml` (Windows `.exe`, macOS `.dmg`, Linux AppImage). Prefer source install for development; use release assets for end-user distribution when available.

## Install failures checklist

1. Confirm Python version: `python --version` (use 3.12 if system Python is 3.14+)
2. Upgrade packaging tools: `pip install --upgrade pip setuptools wheel`
3. Skip Oracle unless Instant Client is present
4. On Linux, install system PyQt6 packages if Qt plugins fail to load
5. Re-create the virtual environment if imports resolve to the wrong tree
