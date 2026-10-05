# Example 02 — Encrypted connection store

Demonstrates Fernet-backed persistence used by the desktop app (`SecureStore`).

## Prerequisites

Same install as [Example 01](example-01.md). Data is written under the real user data directory (`~/.config/db-storage-manager/` on Linux/macOS).

## Script

```python
from db_storage_manager.config import DEFAULT_SETTINGS, USER_DATA_DIR
from db_storage_manager.security.store import SecureStore


def main() -> None:
    store = SecureStore()

    profiles = [
        {
            "id": "ex-02",
            "name": "demo-sqlite",
            "type": "sqlite",
            "database": ":memory:",
        }
    ]
    store.save_connections(profiles)
    loaded = store.get_connections()
    assert loaded[0]["id"] == "ex-02"

    settings = {**DEFAULT_SETTINGS, "theme": "light"}
    store.set_settings(settings)
    assert store.get_settings()["theme"] == "light"

    print("user data dir:", USER_DATA_DIR)
    print("connections:", loaded)
    print("theme:", store.get_settings()["theme"])


if __name__ == "__main__":
    main()
```

## Expected outcome

- Round-trip of connection profiles succeeds
- Settings persist `theme=light`
- Files appear under the user data directory (`connections.enc`, `settings.enc`, `.master-key`)

## Cleanup note

Removing `.master-key` makes previously encrypted files unreadable. Prefer deleting only test profiles via the API/UI rather than wiping the key on shared machines.
