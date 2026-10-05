# Example 01 — SQLite storage analysis

Real local workflow using the packaged async driver API (validated during the 1.0.2 release pass on Python 3.12).

## Prerequisites

```bash
cd DB_Storage_Manager
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Script

```python
import asyncio
import tempfile
from pathlib import Path

from db_storage_manager.db import ConnectionConfig, DatabaseConnectionFactory


async def main() -> None:
    db_path = Path(tempfile.mkdtemp()) / "example01.db"
    cfg = ConnectionConfig(
        id="ex-01",
        name="example-sqlite",
        type="sqlite",
        database=str(db_path),
    )
    conn = DatabaseConnectionFactory.create_connection(cfg)

    assert await conn.test_connection() is True

    await conn.connect()
    await conn.execute_query(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
        safe_mode=False,
    )
    await conn.execute_query(
        "INSERT INTO items(name) VALUES ('alpha')",
        safe_mode=False,
    )

    try:
        await conn.execute_query(
            "INSERT INTO items(name) VALUES ('blocked')",
            safe_mode=True,
        )
    except ValueError as exc:
        print("safe mode blocked write:", exc)

    result = await conn.execute_query("SELECT * FROM items", safe_mode=True)
    print("rows:", result["rows"])

    analysis = await conn.analyze_storage()
    print("tableCount:", analysis["tableCount"], "totalSize:", analysis["totalSize"])

    await conn.disconnect()
    print("database file:", db_path, "exists=", db_path.exists())


if __name__ == "__main__":
    asyncio.run(main())
```

## Expected outcome

- Safe mode raises `ValueError` for the blocked INSERT
- SELECT returns one row `{'id': 1, 'name': 'alpha'}`
- Analysis reports `tableCount` of at least `1` and a positive `totalSize`
