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
| GET | `/api/v1/connections/import/platforms` | OAuth / env import guides (no secrets) |
| POST | `/api/v1/connections/import/env` | Body `{ "path": "/path/.env", "save": false }` — parse profiles (redacted); `save: true` writes SecureStore |
| POST | `/api/v1/connections/import/ssh` | Body `{ "path": "/path/KEY-or-dir", "save": false }` — SSH bastion profile from key + sidecars |
| GET | `/api/v1/backups` | Local backups (`?backup_dir=` optional) |
| POST | `/api/v1/backups/{id}/verify` | SHA-256 verify |
| POST | `/api/v1/backups/{id}/dry-run` | Checksum + payload dry-run (no live DB write) |
| GET | `/` | Minimal Web UI |

Set `DSM_API_TOKEN` and/or create a SecureStore pairing token (`db-storage-manager-pair`) to require Bearer auth on all routes except health. See [cli.md](cli.md) and [privacy-companion.md](privacy-companion.md).

### Companion export (Python)

```python
from db_storage_manager.export import export_companion_bundle

bundle = export_companion_bundle()  # passwords redacted
# export_companion_bundle(include_secrets=True, consent=True)  # desktop only
```

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

### Public SDK (`db_storage_manager.plugins.sdk`)

Stable authoring surface (API version `1.0`):

```python
from db_storage_manager.plugins.sdk import (
    PLUGIN_API_VERSION,
    Plugin,
    PluginMetadata,
    PluginType,
    load_manifest,
    validate_manifest,
    ManifestError,
)
```

A third-party plugin is a directory containing `plugin.json` plus an entry module:

```json
{
  "id": "hello_echo",
  "name": "Hello Echo",
  "version": "1.0.0",
  "author": "VoxHash Technologies",
  "description": "Example SDK plugin",
  "plugin_type": "custom",
  "api_version": "1.0",
  "entry": "plugin:HelloEchoPlugin",
  "dependencies": []
}
```

`entry` is `module:ClassName` relative to the plugin root. The class must subclass `Plugin`. See `examples/plugins/hello_echo/`.

### Premium plugins (optional `license` block)

A plugin without a `license` block is free. To sell a plugin through [LicenseChain](https://licensechain.app), create a product in the LicenseChain dashboard (or run `python scripts/licensechain_products.py path/to/plugin --apply`) and add its id:

```json
{
  "license": {
    "provider": "licensechain",
    "product_id": "<LicenseChain product UUID>",
    "pricing": { "currency": "USD", "monthly": 1.99, "yearly": 16.00, "one_time": 24.00 }
  }
}
```

- `product_id` is required; `purchase_url` defaults to `https://pay.licensechain.app/checkout/<product_id>`; `provider` must be `licensechain`. Unknown or malformed values reject the manifest (fail closed)
- Provisioned LicenseChain product ids for the bundle and each planned premium plugin are in `db_storage_manager.plugins.pricing.PREMIUM_PRODUCT_IDS` (monthly, yearly, one-time per entry)
- A licence for any bundle product (`PREMIUM_PRODUCT_IDS["bundle"]`: monthly, yearly or one-time) also unlocks every plugin whose `product_id` is one of the first-party ids in `PREMIUM_PRODUCT_IDS`; see `plugins.pricing.accepted_product_ids`. A plugin-only key unlocks only that plugin, and third-party `product_id`s are matched exactly
- `pricing` is display-only (shown in the licence prompt); LicenseChain holds the authoritative price. Options: `monthly`, `yearly`, `one_time`, positive amounts, 3-letter uppercase `currency`. First-party plugins stay at or under `plugins.sdk.PRICING_TIERS["plugin"]`
- The host checks the licence before importing plugin code (install), on enable and on every execution. Plugins never see the licence key. Built-in plugins ignore the block
- Python: `LocalPluginMarketplace.activate_license(plugin_id, key, email=None)`, `deactivate_license`, `license_status`, `require_license`; `install_from_path(path, license_key=..., license_email=...)`. A missing licence raises `PluginLicenseRequired`

### PITR Verify (`pitr-verify`)

First premium plugin. It is not a built-in: install the directory from `db_storage_manager.premium_plugins.bundled_plugin_dir("pitr-verify")`. Installing requires `plugins:manage`. `execute` requires `monitoring:read`.

`license.product_id` is `plugins.pricing.PREMIUM_PRODUCT_IDS["pitr-verify"]["monthly"]` (the products were created earlier; do not run `licensechain_products.py --apply` again for this plugin).

```python
from db_storage_manager.plugins.loader import load_plugin_from_directory
from db_storage_manager.premium_plugins import bundled_plugin_dir

plugin = load_plugin_from_directory(bundled_plugin_dir("pitr-verify"))
report = plugin.execute(connection, expected_retention_days=7)
```

`report["status"]` is `ok`, `fail` or `not_available`. `pitr_enabled` is true, false, or null when the check could not be read (permission denied, provider 401/403, or a field the API did not return). Self-hosted PostgreSQL is decided from `wal_level`, `archive_mode`, `archive_command` / `archive_library` and `pg_stat_archiver`. That view does not include how long WAL is retained, so `expected_retention_days` on a self-hosted server is `not_available` rather than a guessed match.

When `connection.config.extra["cloud_provider"]` is set, retention comes from the provider and the catalog is attached as extra checks. Supported values: `aws_rds` (Aurora PostgreSQL uses `DescribeDBClusters`), `gcp_cloudsql`, `azure_postgres` (flexible server; `resource_group` is required), `supabase` (`DSM_SUPABASE_ACCESS_TOKEN`), `neon` (`NEON_API_KEY`). `cloud_instance_id` is the instance, server, project ref or project id. Credentials are the operator's (SecureStore / environment); none are bundled. `azure_sql` is reported `not_available` because it is SQL Server.

### Local marketplace

```python
from pathlib import Path
from db_storage_manager.plugins.marketplace import LocalPluginMarketplace

mp = LocalPluginMarketplace()
mp.list_installed()  # builtins + user installs
mp.install_from_path(Path("examples/plugins/hello_echo"))
mp.install_from_url("https://example.com/my-plugin.zip")  # zip or tar.gz
mp.set_enabled("hello_echo", False)
mp.uninstall("hello_echo")  # user installs only
manager = mp.load_into_manager()
manager.execute_plugin("hello_echo", message="hi")
```

Registry files live under `~/.config/db-storage-manager/plugins/` (`registry.json`, `installed/`). Enable/disable flags are stored in SecureStore settings key `plugins`. There is no remote catalog with placeholder listings; a future public store can publish the same `plugin.json` layout.
