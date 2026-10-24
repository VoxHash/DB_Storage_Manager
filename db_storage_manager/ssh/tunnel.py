"""
SSH tunneling implementation (Paramiko local port forward).
"""

from __future__ import annotations

import asyncio
import select
import socket
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from paramiko import AutoAddPolicy, SSHClient


class SSHTunnelError(Exception):
    """Raised when an SSH tunnel cannot be established or used."""


def normalize_ssh_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a normalized ssh_config dict suitable for persistence / TunnelManager."""
    raw = raw or {}
    enabled = bool(raw.get("enabled", False))
    try:
        ssh_port = int(raw.get("ssh_port") or 22)
    except (TypeError, ValueError):
        ssh_port = 22
    try:
        remote_port = int(raw.get("remote_port") or 5432)
    except (TypeError, ValueError):
        remote_port = 5432

    key_path = (raw.get("ssh_key_path") or "").strip() or None
    password = raw.get("ssh_password") or None
    if isinstance(password, str) and password == "":
        password = None

    return {
        "enabled": enabled,
        "ssh_host": (raw.get("ssh_host") or "").strip(),
        "ssh_port": ssh_port,
        "ssh_username": (raw.get("ssh_username") or "").strip(),
        "ssh_password": password,
        "ssh_key_path": key_path,
        "remote_host": (raw.get("remote_host") or "localhost").strip() or "localhost",
        "remote_port": remote_port,
    }


def validate_ssh_config(ssh_config: Dict[str, Any]) -> None:
    """Validate required fields when a tunnel is enabled. Raises SSHTunnelError."""
    cfg = normalize_ssh_config(ssh_config)
    if not cfg["enabled"]:
        raise SSHTunnelError("SSH tunnel is not enabled for this connection")
    if not cfg["ssh_host"]:
        raise SSHTunnelError("SSH bastion host is required")
    if not cfg["ssh_username"]:
        raise SSHTunnelError("SSH username is required")
    if not (1 <= cfg["ssh_port"] <= 65535):
        raise SSHTunnelError("SSH port must be between 1 and 65535")
    if not (1 <= cfg["remote_port"] <= 65535):
        raise SSHTunnelError("Remote database port must be between 1 and 65535")
    if not cfg["remote_host"]:
        raise SSHTunnelError("Remote host (as seen from the bastion) is required")

    key_path = cfg["ssh_key_path"]
    if key_path:
        path = Path(key_path).expanduser()
        if not path.is_file():
            raise SSHTunnelError(f"SSH private key not found: {path}")
    elif not cfg["ssh_password"]:
        raise SSHTunnelError(
            "Provide an SSH private key path or an SSH password for authentication"
        )


def format_ssh_error(exc: BaseException) -> str:
    """Map Paramiko / socket failures to a short user-facing message."""
    name = type(exc).__name__
    msg = str(exc).strip() or name
    lowered = msg.lower()
    if "authentication" in lowered or name in {"AuthenticationException", "BadAuthenticationType"}:
        return f"SSH authentication failed: {msg}"
    if "timed out" in lowered or "timeout" in lowered:
        return f"SSH connection timed out: {msg}"
    if "name or service not known" in lowered or "nodename nor servname" in lowered:
        return f"SSH host could not be resolved: {msg}"
    if "connection refused" in lowered:
        return f"SSH connection refused: {msg}"
    if "no such file" in lowered or "private key" in lowered:
        return f"SSH key error: {msg}"
    return f"SSH tunnel error ({name}): {msg}"


class SSHTunnel:
    """SSH local port-forward tunnel for secure database access."""

    def __init__(
        self,
        ssh_host: str,
        ssh_port: int = 22,
        ssh_username: str = "",
        ssh_password: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        remote_host: str = "localhost",
        remote_port: int = 5432,
        local_port: Optional[int] = None,
        connect_timeout: float = 20.0,
    ):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_key_path = ssh_key_path
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_port = local_port or self._find_free_port()
        self.connect_timeout = connect_timeout

        self.ssh_client: Optional[SSHClient] = None
        self.transport = None
        self.tunnel_active = False
        self._last_error: Optional[str] = None

        self._server_socket: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._forward_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @staticmethod
    def _find_free_port() -> int:
        """Find a free local TCP port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @classmethod
    def from_ssh_config(
        cls,
        ssh_config: Dict[str, Any],
        local_port: Optional[int] = None,
    ) -> "SSHTunnel":
        """Build a tunnel from a normalized (or raw) connection ssh_config."""
        cfg = normalize_ssh_config(ssh_config)
        validate_ssh_config(cfg)
        return cls(
            ssh_host=cfg["ssh_host"],
            ssh_port=cfg["ssh_port"],
            ssh_username=cfg["ssh_username"],
            ssh_password=cfg["ssh_password"],
            ssh_key_path=cfg["ssh_key_path"],
            remote_host=cfg["remote_host"],
            remote_port=cfg["remote_port"],
            local_port=local_port,
        )

    def connect_sync(self) -> None:
        """Establish the SSH session and start local port forwarding."""
        with self._lock:
            if self.tunnel_active and self.is_active():
                return
            self.disconnect_sync()

            validate_ssh_config(
                {
                    "enabled": True,
                    "ssh_host": self.ssh_host,
                    "ssh_port": self.ssh_port,
                    "ssh_username": self.ssh_username,
                    "ssh_password": self.ssh_password,
                    "ssh_key_path": self.ssh_key_path,
                    "remote_host": self.remote_host,
                    "remote_port": self.remote_port,
                }
            )

            client = SSHClient()
            client.set_missing_host_key_policy(AutoAddPolicy())

            connect_kwargs: Dict[str, Any] = {
                "hostname": self.ssh_host,
                "port": self.ssh_port,
                "username": self.ssh_username,
                "timeout": self.connect_timeout,
                "allow_agent": True,
                "look_for_keys": False,
            }

            try:
                if self.ssh_key_path:
                    key_path = str(Path(self.ssh_key_path).expanduser())
                    connect_kwargs["key_filename"] = key_path
                    if self.ssh_password:
                        connect_kwargs["passphrase"] = self.ssh_password
                else:
                    connect_kwargs["password"] = self.ssh_password
                    connect_kwargs["look_for_keys"] = False

                client.connect(**connect_kwargs)
                transport = client.get_transport()
                if transport is None:
                    raise SSHTunnelError("SSH transport unavailable after connect")
                transport.set_keepalive(30)

                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", self.local_port))
                server.listen(64)
                server.settimeout(1.0)
                self.local_port = int(server.getsockname()[1])

                self.ssh_client = client
                self.transport = transport
                self._server_socket = server
                self._stop_event.clear()
                self._forward_thread = threading.Thread(
                    target=self._accept_loop,
                    name=f"ssh-tunnel-{self.local_port}",
                    daemon=True,
                )
                self._forward_thread.start()
                self.tunnel_active = True
                self._last_error = None
            except SSHTunnelError as exc:
                self._last_error = str(exc)
                self._cleanup_resources(client=client)
                raise
            except Exception as exc:
                message = format_ssh_error(exc)
                self._last_error = message
                self._cleanup_resources(client=client)
                raise SSHTunnelError(message) from exc

    async def connect(self) -> None:
        """Async wrapper around connect_sync."""
        await asyncio.to_thread(self.connect_sync)

    def disconnect_sync(self) -> None:
        """Stop forwarding and close the SSH session."""
        with self._lock:
            self._stop_event.set()
            self._cleanup_resources()
            self.tunnel_active = False

    async def disconnect(self) -> None:
        """Async wrapper around disconnect_sync."""
        await asyncio.to_thread(self.disconnect_sync)

    def _cleanup_resources(self, client: Optional[SSHClient] = None) -> None:
        server = self._server_socket
        self._server_socket = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

        thread = self._forward_thread
        self._forward_thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        active_client = self.ssh_client or client
        self.ssh_client = None
        self.transport = None
        if active_client is not None:
            try:
                active_client.close()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        assert self._server_socket is not None
        server = self._server_socket
        while not self._stop_event.is_set():
            try:
                client_sock, peeraddr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            worker = threading.Thread(
                target=self._bridge,
                args=(client_sock, peeraddr),
                daemon=True,
            )
            worker.start()

    def _bridge(self, client_sock: socket.socket, peeraddr: Tuple[str, int]) -> None:
        channel = None
        try:
            transport = self.transport
            if transport is None or not transport.is_active():
                client_sock.close()
                return
            channel = transport.open_channel(
                "direct-tcpip",
                (self.remote_host, self.remote_port),
                peeraddr,
            )
            if channel is None:
                client_sock.close()
                return

            client_sock.setblocking(False)
            while not self._stop_event.is_set():
                r, _, x = select.select([client_sock, channel], [], [client_sock, channel], 1.0)
                if x:
                    break
                if client_sock in r:
                    data = client_sock.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in r:
                    if channel.recv_ready():
                        data = channel.recv(65536)
                        if not data:
                            break
                        client_sock.sendall(data)
                    if channel.closed or channel.exit_status_ready():
                        break
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except OSError:
                pass
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass

    def get_local_endpoint(self) -> Dict[str, Any]:
        """Local endpoint applications should use once the tunnel is up."""
        return {
            "host": "127.0.0.1",
            "port": self.local_port,
        }

    def is_active(self) -> bool:
        """True when the tunnel thread and SSH transport are alive."""
        transport_ok = (
            self.transport is not None
            and getattr(self.transport, "is_active", lambda: False)()
        )
        thread_ok = self._forward_thread is not None and self._forward_thread.is_alive()
        return bool(self.tunnel_active and transport_ok and thread_ok)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def status(self) -> Dict[str, Any]:
        """Snapshot for UI / TunnelManager.list_tunnels."""
        return {
            "active": self.is_active(),
            "localHost": "127.0.0.1",
            "localPort": self.local_port,
            "remoteHost": self.remote_host,
            "remotePort": self.remote_port,
            "sshHost": self.ssh_host,
            "sshPort": self.ssh_port,
            "lastError": self._last_error,
        }


class TunnelManager:
    """Manage multiple SSH tunnels keyed by connection id."""

    def __init__(self):
        self.tunnels: Dict[str, SSHTunnel] = {}
        self._lock = threading.RLock()

    def create_tunnel_sync(
        self,
        tunnel_id: str,
        ssh_host: str = "",
        ssh_port: int = 22,
        ssh_username: str = "",
        ssh_password: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        remote_host: str = "localhost",
        remote_port: int = 5432,
        ssh_config: Optional[Dict[str, Any]] = None,
    ) -> SSHTunnel:
        """Create (or replace) and start a tunnel. Prefer ssh_config when provided."""
        with self._lock:
            if tunnel_id in self.tunnels:
                self.close_tunnel_sync(tunnel_id)

            if ssh_config is not None:
                tunnel = SSHTunnel.from_ssh_config(ssh_config)
            else:
                tunnel = SSHTunnel(
                    ssh_host=ssh_host,
                    ssh_port=ssh_port,
                    ssh_username=ssh_username,
                    ssh_password=ssh_password,
                    ssh_key_path=ssh_key_path,
                    remote_host=remote_host,
                    remote_port=remote_port,
                )
            tunnel.connect_sync()
            self.tunnels[tunnel_id] = tunnel
            return tunnel

    async def create_tunnel(
        self,
        tunnel_id: str,
        ssh_host: str = "",
        ssh_port: int = 22,
        ssh_username: str = "",
        ssh_password: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        remote_host: str = "localhost",
        remote_port: int = 5432,
        ssh_config: Optional[Dict[str, Any]] = None,
    ) -> SSHTunnel:
        return await asyncio.to_thread(
            self.create_tunnel_sync,
            tunnel_id,
            ssh_host,
            ssh_port,
            ssh_username,
            ssh_password,
            ssh_key_path,
            remote_host,
            remote_port,
            ssh_config,
        )

    def close_tunnel_sync(self, tunnel_id: str) -> None:
        with self._lock:
            tunnel = self.tunnels.pop(tunnel_id, None)
            if tunnel is not None:
                tunnel.disconnect_sync()

    async def close_tunnel(self, tunnel_id: str) -> None:
        await asyncio.to_thread(self.close_tunnel_sync, tunnel_id)

    def close_all_tunnels_sync(self) -> None:
        with self._lock:
            ids = list(self.tunnels.keys())
        for tunnel_id in ids:
            self.close_tunnel_sync(tunnel_id)

    async def close_all_tunnels(self) -> None:
        await asyncio.to_thread(self.close_all_tunnels_sync)

    def get_tunnel(self, tunnel_id: str) -> Optional[SSHTunnel]:
        return self.tunnels.get(tunnel_id)

    def list_tunnels(self) -> Dict[str, Dict[str, Any]]:
        return {
            tunnel_id: tunnel.status()
            for tunnel_id, tunnel in self.tunnels.items()
        }
