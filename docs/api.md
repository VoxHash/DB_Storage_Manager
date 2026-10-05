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

## Secure storage

```python
from db_storage_manager.security.store import SecureStore

store = SecureStore()
store.save_connections([...])
connections = store.get_connections()
store.set_settings({...})
settings = store.get_settings()
```

## SSH

```python
from db_storage_manager.ssh import SSHTunnel, TunnelManager
```

## GUI entry (advanced)

```python
from db_storage_manager.main import main
from db_storage_manager.gui.main_window import MainWindow
```

Prefer the documented CLI entry for end users. GUI classes expect a running `QApplication`.

## Plugins and extensions

Plugin hooks live under `db_storage_manager.plugins` (`base`, `registry`, migration/comparison helpers). Treat these as evolving APIs; pin versions for production automation.
