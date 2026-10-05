# Troubleshooting

## Application will not start

- Confirm Python 3.10–3.12: `python --version`
- Recreate the venv and reinstall: `pip install -r requirements.txt && pip install -e .`
- On Linux, install system Qt helpers: `sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtcharts`
- Check for missing imports: `python -c "import PyQt6; import db_storage_manager"`

## `pip install -r requirements.txt` fails on `cx_Oracle`

Oracle support is optional. Current `requirements.txt` excludes `cx_Oracle` from the core install. If you still try `pip install cx_Oracle` without Instant Client / build deps, pip may fail with `pkg_resources` or compile errors. Use core install without Oracle, or install Instant Client first, then `pip install -e ".[oracle]"`.

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
