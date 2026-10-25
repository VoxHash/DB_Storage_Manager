# API

Public Python surfaces useful for automation, tests, and plugins. Import from the installed `db_storage_manager` package.

## Package metadata

```python
from db_storage_manager import __version__, __author__
```

## Configuration

```python
from db_storage_manager.config import (
    APP_NAME,
    APP_VERSION,
    USER_DATA_DIR,
    CONNECTIONS_FILE,
    SETTINGS_FILE,
    DEFAULT_SETTINGS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
)
```

## Connection factory

```python
from db_storage_manager.db import (
    ConnectionConfig,
    DatabaseConnectionFactory,
)

cfg = ConnectionConfig(
    id="local-1",
    name="demo",
    type="sqlite",
    database="/tmp/demo.db",
)
conn = DatabaseConnectionFactory.create_connection(cfg)
```

All driver methods are **async**:

```python
import asyncio

async def run():
    await conn.connect()
    result = await conn.execute_query("SELECT 1 AS n", safe_mode=True)
    analysis = await conn.analyze_storage()
    await conn.disconnect()
    return result, analysis

asyncio.run(run())
```

Abstract methods on `DatabaseConnection`: `connect`, `disconnect`, `analyze_storage`, `execute_query`, `get_schema`, `create_backup`, `restore_backup`, plus `test_connection`.

## REST companion (local HTTP)

```bash
python -m db_storage_manager.api --host 127.0.0.1 --port 8765
```

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/health` | Liveness (no auth) |
| GET | `/api/v1/info` | Version + native backend |
| GET | `/api/v1/connections` | SecureStore profiles; passwords redacted |
| GET | `/api/v1/backups` | Local backups (`?backup_dir=` optional) |
| POST | `/api/v1/backups/{id}/verify` | SHA-256 verify |
| POST | `/api/v1/backups/{id}/dry-run` | Checksum + payload dry-run (no live DB write) |
| GET | `/` | Minimal Web UI |

Set `DSM_API_TOKEN` to require Bearer auth on all routes except health. See [cli.md](cli.md).

## Native performance helpers

```python
from db_storage_manager.native import (
    backend_info,
    is_available,
    gzip_compress_file,
    gzip_decompress_file,
    zstd_compress_file,
    zstd_decompress_file,
    encrypt_file,
    decrypt_file,
    sha256_file,
    sha256_files_parallel,
    aggregate_f64,
    hash_rows_parallel,
)

backend_info()  # {'available': True, 'language': 'rust', ...} or Python fallback
# encrypt_file / decrypt_file use DSMENC1 (AES-256-GCM + PBKDF2); native ↔ Python compatible
```

Install a Release wheel or build with maturin (see [installation.md](installation.md)). Backup verification:

```python
from db_storage_manager.backups.manager import BackupManager

manager = BackupManager()
manager.verify_backup_checksum(backup_info)
manager.verify_backups_parallel([backup_info, ...])
manager.dry_run_restore(backup_info)  # checksum + payload checks; never writes to a live DB
manager.dry_run_restore(backup_info, encryption_key="passphrase")  # encrypted backups
```

`verify_*` results include `ok`, `status` (`pass` / `fail` / `missing_checksum` / `not_found`), and digests. Local backups persist SHA-256 in a `.meta.json` sidecar next to the backup file. Passphrases are never written to sidecars.


## Secure storage

```python
from db_storage_manager.security.store import SecureStore

store = SecureStore()
store.save_connections([...])
connections = store.get_connections()
store.set_settings({...})
settings = store.get_settings()
```

## Monitoring

```python
from db_storage_manager.monitoring import (
    AlertManager,
    DatabaseMonitor,
)

monitor = DatabaseMonitor(connection)  # async DatabaseConnection
data = await monitor.poll_once()
# data["metrics"], data["health"], data["alerts"], data["alertCounts"]

manager = AlertManager()
manager.check_metrics({"activeConnections": 80, "cacheHitRatio": 55})
manager.acknowledge_by_id(manager.get_active_alerts()[0].id)
manager.acknowledge_all()
counts = manager.get_counts()  # critical / warning / info / total
```

`DatabaseMonitor.poll_once()` collects metrics, runs health checks, evaluates thresholds (with dedupe for active alerts), and returns `get_dashboard_data()`.

## SSH

```python
from db_storage_manager.ssh import (
    SSHTunnel,
    SSHTunnelError,
    TunnelManager,
    normalize_ssh_config,
    validate_ssh_config,
)

manager = TunnelManager()
tunnel = manager.create_tunnel_sync(
    "conn-id",
    ssh_config={
        "enabled": True,
        "ssh_host": "bastion.example.com",
        "ssh_port": 22,
        "ssh_username": "deploy",
        "ssh_password": None,
        "ssh_key_path": "~/.ssh/id_ed25519",
        "remote_host": "localhost",
        "remote_port": 5432,
    },
)
endpoint = tunnel.get_local_endpoint()  # {"host": "127.0.0.1", "port": ...}
manager.close_tunnel_sync("conn-id")
```

`SSHTunnelError` carries clear messages for missing fields, bad keys, auth failures, timeouts, and refused connections.

## GUI entry (advanced)

```python
from db_storage_manager.main import main
from db_storage_manager.gui.main_window import MainWindow
```

Prefer the documented CLI entry for end users. GUI classes expect a running `QApplication`.

## Plugins and extensions

Plugin hooks live under `db_storage_manager.plugins` (`base`, `registry`, migration/comparison helpers). Treat these as evolving APIs; pin versions for production automation.
