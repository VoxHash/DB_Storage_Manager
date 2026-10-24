# Troubleshooting

## Application will not start

- Confirm Python 3.10–3.12: `python --version`
- Recreate the venv and reinstall: `pip install -r requirements.txt && pip install -e .`
- On Linux, install system Qt helpers: `sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtcharts`
- Check for missing imports: `python -c "import PyQt6; import db_storage_manager"`

## Optional engine ImportError (oracle / mssql / clickhouse / influxdb)

Selecting an optional engine without its Python package raises an `ImportError` that names the package and the setup extra. Install only what you need:

```bash
pip install -e ".[oracle]"       # oracledb (Thin mode; no Instant Client by default)
pip install -e ".[mssql]"        # pyodbc (+ host ODBC Driver 18)
pip install -e ".[clickhouse]"   # clickhouse-driver
pip install -e ".[influxdb]"     # influxdb-client
pip install -e ".[engines]"      # all of the above Python packages
```

See [installation.md](installation.md) for Instant Client / ODBC platform steps.

## Oracle: legacy `cx_Oracle` / Instant Client build failures

Oracle support uses **`oracledb`** (python-oracledb), not `cx_Oracle`. Thin mode needs no Instant Client. Do not add `cx_Oracle` to a fresh environment.

- Core `requirements.txt` never installs Oracle drivers.
- If you previously used Instant Client only to make `cx_Oracle` build: switch to `pip install -e ".[oracle]"` and use Thin mode unless you need Thick features.
- Thick mode: install Instant Client, set `ORACLE_CLIENT_LIB_DIR`, then connect.

## SQL Server: `pyodbc` installed but connection fails / no ODBC driver

- List drivers: `odbcinst -q -d` (Linux/macOS) or the Windows ODBC Data Source Administrator.
- Expect `ODBC Driver 18 for SQL Server` (or 17). Install per [installation.md](installation.md).
- On macOS use **unixODBC** (Homebrew), not iODBC, to avoid architecture mismatches with Microsoft’s driver.
- Linux builds of `pyodbc` from source need `unixodbc-dev` (Debian/Ubuntu) or equivalent headers.
- On Arch / Garuda: `unixodbc` via pacman + AUR `msodbcsql` (Driver 18). Empty `/etc/odbcinst.ini` means no driver is registered — run `./scripts/setup-host-odbc-arch.sh` (sudo).

## Database connection fails

- Verify host, port, database name, and credentials
- Confirm the server is listening and reachable through firewalls
- For remote engines, configure SSH tunneling when required
- Optional engine missing → install the matching extra (see [installation.md](installation.md))
- `test_connection()` returning `False` indicates connect/disconnect failed without raising to the caller

## Safe mode blocks my query

Expected for writes. Disable Safe Mode only when intentional. Error text resembles: `Only SELECT queries are allowed in safe mode`.

## Analysis fails or is slow

- Confirm the DB user can read catalog/system tables
- Large databases take longer; watch for UI progress/errors
- Verify the selected connection type matches the server

## Backup failures

- Check free disk space and write permissions on `backups/`
- For S3/Google Drive, validate credentials, bucket/folder, and network access
- Ensure the source database connection still works

## Encryption / settings issues

- Do not delete `.master-key` unless you intend to lose access to encrypted files
- User data path differs on Windows vs Linux/macOS — see [configuration.md](configuration.md)

## Import or editable install points at the wrong tree

```bash
python -c "import db_storage_manager,sys; print(db_storage_manager.__file__); print(sys.executable)"
```

Reinstall with `pip install -e .` inside the intended venv.

## Still stuck?

Open an issue: https://github.com/VoxHash/DB_Storage_Manager/issues  
Email: contact@voxhash.dev
