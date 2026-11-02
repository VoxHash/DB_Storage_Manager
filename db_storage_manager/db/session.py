"""Prepare ConnectionConfig kwargs, opening SSH tunnels when required."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..ssh import TunnelManager, get_shared_tunnel_manager, validate_ssh_config

CONNECTION_CONFIG_FIELDS = frozenset(
    {
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
)


def connection_config_kwargs(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a connection profile dict to ``ConnectionConfig`` fields."""
    return {k: v for k, v in connection.items() if k in CONNECTION_CONFIG_FIELDS}


def tunnel_id_for_connection(connection: Dict[str, Any]) -> str:
    """Stable TunnelManager key for a connection profile."""
    return str(connection.get("id") or connection.get("name") or "session")


def ensure_tunnel_for_connection(
    connection: Dict[str, Any],
    *,
    tunnel_manager: Optional[TunnelManager] = None,
) -> Dict[str, Any]:
    """Return driver kwargs pointed at a local SSH forward when SSH is enabled.

    Mirrors Connections test / import probe behavior: open (or reuse) a tunnel,
    rewrite ``host``/``port`` to the local endpoint, and clear ``ssh_config`` /
    ``connection_string`` so drivers do not bypass the tunnel.
    """
    manager = tunnel_manager or get_shared_tunnel_manager()
    kwargs = connection_config_kwargs(connection)
    ssh_config = connection.get("ssh_config") or {}
    if not ssh_config.get("enabled"):
        return kwargs

    connection_id = tunnel_id_for_connection(connection)
    validate_ssh_config(ssh_config)
    tunnel = manager.get_tunnel(connection_id)
    if tunnel is None or not tunnel.is_active():
        tunnel = manager.create_tunnel_sync(connection_id, ssh_config=ssh_config)
    endpoint = tunnel.get_local_endpoint()
    kwargs["host"] = endpoint["host"]
    kwargs["port"] = endpoint["port"]
    kwargs["ssh_config"] = None
    # URL-style DSNs would still target the remote host/port
    kwargs["connection_string"] = None
    return kwargs
