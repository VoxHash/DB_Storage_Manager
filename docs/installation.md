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

Core install covers PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, and Redis. Optional engines are **not** in `requirements.txt`; install only what you need via setup extras.

| Engine | Extra | PyPI package | System prerequisites |
|---|---|---|---|
| Oracle | `pip install -e ".[oracle]"` | [`oracledb`](https://pypi.org/project/oracledb/) (python-oracledb) | **Thin mode (default):** none — connects without Instant Client (Oracle Database 12.1+). **Thick mode:** Oracle Instant Client 19+ when you need 11g, Native Network Encryption, or Application Continuity |
| SQL Server | `pip install -e ".[mssql]"` | [`pyodbc`](https://pypi.org/project/pyodbc/) | Microsoft **ODBC Driver 18** for SQL Server (17 still accepted) + unixODBC on Linux/macOS |
| ClickHouse | `pip install -e ".[clickhouse]"` | [`clickhouse-driver`](https://pypi.org/project/clickhouse-driver/) | None (wheels on Linux / macOS / Windows) |
| InfluxDB 2.x | `pip install -e ".[influxdb]"` | [`influxdb-client`](https://pypi.org/project/influxdb-client/) | None (HTTP client) |
| All optional engines | `pip install -e ".[engines]"` | oracledb + pyodbc + clickhouse-driver + influxdb-client | SQL Server still needs the host ODBC driver; Oracle Thick mode still needs Instant Client if you enable it |

Missing optional drivers raise a clear `ImportError` when that engine is selected, including the matching `pip install -e ".[…]"` hint and a short platform note.

```bash
# Examples
pip install -e ".[mssql,clickhouse,influxdb]"
pip install -e ".[oracle]"
pip install -e ".[engines]"
```

### Oracle Instant Client (Thick mode only)

Default `oracledb` **Thin** mode needs no Oracle Client libraries. Enable Thick mode only when required (Oracle 11g, NNE/checksumming, AC/TAC):

1. Install [Oracle Instant Client](https://www.oracle.com/database/technologies/instant-client/downloads.html) Basic or Basic Light (19, 21, or 23) for your OS/arch.
2. Point the library directory at the client, then connect:

```bash
export ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient_23_5   # example path
```

DB Storage Manager calls `oracledb.init_oracle_client(lib_dir=…)` when `ORACLE_CLIENT_LIB_DIR` is set. Legacy `cx_Oracle` is obsolete; if it is already installed it is used as a fallback, but new installs should use `oracledb`.

Docs: [Installing python-oracledb](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html), [Thick mode](https://python-oracledb.readthedocs.io/en/latest/user_guide/initialization.html).

### SQL Server ODBC (per platform)

`pyodbc` talks to SQL Server through an ODBC driver manager. Install **Microsoft ODBC Driver 18** (preferred; 17 works). Official guides: [Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server), [macOS](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos), [Windows](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server).

**Debian / Ubuntu** (after adding the [Microsoft package repo](https://packages.microsoft.com/)):

```bash
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev libgssapi-krb5-2
pip install -e ".[mssql]"
```

**RHEL / Fedora / Oracle Linux** — use Microsoft’s `msodbcsql18` packages from the same docs (EULA via `ACCEPT_EULA=Y` or `/opt/microsoft/msodbcsql18/ACCEPT_EULA`).

**Arch Linux / Garuda / Manjaro** (AUR package `msodbcsql` = Microsoft ODBC Driver 18; `unixodbc` from official repos):

```bash
# Interactive (sudo password required), or use the helper:
./scripts/setup-host-odbc-arch.sh

# Manual equivalent:
sudo pacman -S --needed unixodbc
# paru or yay:
ACCEPT_EULA=Y paru -S --needed msodbcsql
odbcinst -q -d   # expect "ODBC Driver 18 for SQL Server" (or similar)
pip install -e ".[mssql]"
```

If `/etc/odbcinst.ini` is empty and `odbcinst -q -d` fails, the Microsoft driver is not registered yet — finish the AUR install above (needs sudo). Oracle Instant Client is **not** required for default Thin `oracledb`; skip it unless you need Thick mode.

**macOS (Homebrew):**

```bash
brew install unixodbc
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew trust microsoft/mssql-release
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18
pip install -e ".[mssql]"
```

**Windows:** install the Microsoft ODBC Driver 18 MSI for your architecture from the download page above, then `pip install -e ".[mssql]"`. Windows includes an ODBC driver manager; no unixODBC step.

The app prefers **ODBC Driver 18**, then 17, then any installed driver whose name contains `SQL Server`. If `pyodbc` is present but no SQL Server ODBC driver is registered, connection setup raises an `ImportError` with these install hints.

### ClickHouse and InfluxDB

No proprietary client install. After `pip install -e ".[clickhouse]"` or `".[influxdb]"`, point the connection at your server (ClickHouse native port default **9000**; InfluxDB HTTP default **8086**, token/org via connection extras).

## System packages (Linux)

```bash
sudo apt-get update
sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtcharts
```

macOS users typically rely on the PyQt6 wheels from pip. Windows users may need the Visual C++ Redistributable if wheel installs fail.

## Optional native performance module (Rust / PyO3)

Hot paths (backup gzip, SHA-256 verification, parallel row hashing, numeric aggregates) can use an in-process Rust extension. The app runs without it via pure-Python fallbacks. Wheels use the Python stable ABI (`abi3-py310`) and work on CPython 3.10+.

### Install from GitHub Release wheels (no Rust toolchain)

CI builds platform wheels (Linux manylinux x86_64, Windows x64, macOS Apple Silicon / arm64) and attaches them to [GitHub Releases](https://github.com/VoxHash/DB_Storage_Manager/releases) on each `v*` tag. Prebuilt macOS Intel (x86_64) wheels are not published; use the release sdist with a Rust toolchain, or run under Rosetta with the arm64 wheel when applicable.

```bash
# Example: download the matching .whl from the release assets, then:
pip install ./db_storage_native-0.1.0-cp310-abi3-*.whl
python -c "from db_storage_manager.native import backend_info; print(backend_info())"
# Expect: {'available': True, 'language': 'rust', ...}
```

Or with `gh`:

```bash
gh release download --repo VoxHash/DB_Storage_Manager --pattern 'db_storage_native-*.whl' --dir /tmp/native-wheels
pip install /tmp/native-wheels/db_storage_native-*.whl
```

### Build from source (developers)

**Prerequisites:** Rust toolchain (`rustc` / `cargo`) and [maturin](https://www.maturin.rs/).

```bash
pip install -e ".[native]"
cd native/db_storage_native
maturin develop --release
cd ../..
python -c "from db_storage_manager.native import backend_info; print(backend_info())"
```

Validate:

```bash
pytest -v tests/test_native.py
```

Workflow: `.github/workflows/native-wheels.yml`

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
3. Skip optional engines until needed; use extras, not a forced `cx_Oracle` install
4. For SQL Server: confirm `odbcinst -q -d` lists `ODBC Driver 18 for SQL Server` (or 17)
5. For Oracle Thick mode only: confirm Instant Client and `ORACLE_CLIENT_LIB_DIR`
6. On Linux, install system PyQt6 packages if Qt plugins fail to load
7. Re-create the virtual environment if imports resolve to the wrong tree
