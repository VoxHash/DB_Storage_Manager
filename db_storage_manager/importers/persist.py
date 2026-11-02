"""Merge imported profiles into SecureStore (local encrypted persistence)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from ..db.base import ConnectionConfig
from ..db.factory import DatabaseConnectionFactory
from ..security.store import SecureStore
from ..ssh import SSHTunnelError, TunnelManager, validate_ssh_config
from .redact import redact_text, summarize_profile


def _profile_signature(conn: Dict[str, Any]) -> Tuple[Any, ...]:
    ssh = conn.get("ssh_config") or {}
    return (
        (conn.get("type") or "").lower(),
        conn.get("host"),
        conn.get("port"),
        conn.get("database"),
        conn.get("username"),
        bool(ssh.get("enabled")),
        ssh.get("ssh_host"),
        ssh.get("ssh_username"),
        ssh.get("ssh_key_path"),
    )


def merge_connections(
    existing: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
    *,
    replace_matching: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge ``incoming`` into ``existing``.

    Returns ``(merged_list, actually_added_or_replaced)``.
    """
    merged = list(existing)
    index = {_profile_signature(c): i for i, c in enumerate(merged)}
    changed: List[Dict[str, Any]] = []
    for profile in incoming:
        sig = _profile_signature(profile)
        if sig in index and replace_matching:
            # Keep stable id when replacing a match
            old = merged[index[sig]]
            profile = dict(profile)
            profile["id"] = old.get("id") or profile.get("id")
            merged[index[sig]] = profile
            changed.append(profile)
        elif sig not in index:
            merged.append(profile)
            index[sig] = len(merged) - 1
            changed.append(profile)
    return merged, changed


def save_imported_connections(
    profiles: List[Dict[str, Any]],
    *,
    store: Optional[SecureStore] = None,
    replace_matching: bool = True,
) -> Dict[str, Any]:
    """Persist imported profiles into SecureStore ``connections.enc`` + SSH index."""
    store = store or SecureStore()
    existing = store.get_connections()
    merged, changed = merge_connections(
        existing, profiles, replace_matching=replace_matching
    )
    store.save_connections(merged)
    for conn in changed:
        ssh = conn.get("ssh_config") or {}
        if ssh.get("enabled"):
            store.upsert_ssh_settings_for_connection(conn)
        else:
            store.remove_ssh_settings_for_connection(str(conn.get("id") or ""))
    return {
        "ok": True,
        "saved": len(changed),
        "total": len(merged),
        "profiles": [summarize_profile(c) for c in changed],
    }


def _connection_config_kwargs(connection: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "id",
        "name",
        "type",
        "host",
        "port",
        "database",
        "username",
        "password",
        "connection_string",
        "ssh_config",
        "extra",
    }
    return {k: v for k, v in connection.items() if k in allowed}


async def probe_connection(
    connection: Dict[str, Any],
    *,
    timeout: float = 20.0,
    tunnel_manager: Optional[TunnelManager] = None,
) -> Dict[str, Any]:
    """Safe Mode / SELECT-only style probe via ``test_connection()``.

    Opens an SSH tunnel when ``ssh_config.enabled`` is set. Never returns
    passwords or private keys — errors are redacted.
    """
    summary = summarize_profile(connection)
    owns_manager = tunnel_manager is None
    manager = tunnel_manager or TunnelManager()
    connection_id = str(connection.get("id") or "probe")
    try:
        kwargs = _connection_config_kwargs(connection)
        ssh_config = connection.get("ssh_config") or {}
        if ssh_config.get("enabled"):
            validate_ssh_config(ssh_config)
            tunnel = await manager.create_tunnel(
                connection_id, ssh_config=ssh_config
            )
            endpoint = tunnel.get_local_endpoint()
            kwargs["host"] = endpoint["host"]
            kwargs["port"] = endpoint["port"]
            kwargs["ssh_config"] = None
            summary["tunnel_local_port"] = endpoint["port"]

        # Apply sslmode from extra for postgres
        extra = connection.get("extra") or {}
        if extra.get("sslmode") and not kwargs.get("extra"):
            kwargs["extra"] = {"sslmode": extra["sslmode"]}
        elif extra.get("sslmode"):
            kwargs["extra"] = dict(kwargs.get("extra") or {})
            kwargs["extra"]["sslmode"] = extra["sslmode"]

        cfg = ConnectionConfig(**kwargs)

        async def _run() -> bool:
            conn = DatabaseConnectionFactory.create_connection(cfg)
            try:
                return bool(await conn.test_connection())
            finally:
                try:
                    await conn.disconnect()
                except Exception:
                    pass

        ok = bool(await asyncio.wait_for(_run(), timeout=timeout))
        return {
            "ok": ok,
            "status": "pass" if ok else "fail",
            "profile": summary,
            "error": None if ok else "test_connection() returned False",
        }
    except SSHTunnelError as exc:
        return {
            "ok": False,
            "status": "fail",
            "profile": summary,
            "error": redact_text(str(exc)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "fail",
            "profile": summary,
            "error": redact_text(f"{type(exc).__name__}: {exc}"),
        }
    finally:
        if owns_manager:
            try:
                await manager.close_tunnel(connection_id)
            except Exception:
                pass
            try:
                await manager.close_all_tunnels()
            except Exception:
                pass


def probe_connection_sync(
    connection: Dict[str, Any], **kwargs: Any
) -> Dict[str, Any]:
    return asyncio.run(probe_connection(connection, **kwargs))
