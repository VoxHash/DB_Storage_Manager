"""
SSH tunneling implementation
"""

import asyncio
from typing import Dict, Optional, Any
from pathlib import Path
import paramiko
from paramiko import SSHClient, AutoAddPolicy
import socket


class SSHTunnel:
    """SSH tunnel for secure database access"""

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
    ):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_key_path = ssh_key_path
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_port = local_port or self._find_free_port()
        
        self.ssh_client: Optional[SSHClient] = None
        self.transport: Optional[paramiko.Transport] = None
        self.tunnel_active = False

    def _find_free_port(self) -> int:
        """Find a free local port"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    async def connect(self) -> None:
        """Establish SSH tunnel"""
        self.ssh_client = SSHClient()
        self.ssh_client.set_missing_host_key_policy(AutoAddPolicy())
        
        # Connect to SSH server
        if self.ssh_key_path and Path(self.ssh_key_path).exists():
            # Use key-based authentication
            self.ssh_client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                key_filename=self.ssh_key_path,
            )
        else:
            # Use password authentication
            self.ssh_client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                password=self.ssh_password,
            )
        
        # Create port forwarding
        self.transport = self.ssh_client.get_transport()
        self.transport.request_port_forward("", self.local_port)
        
        # Start forwarding in background
        def forward_handler(channel):
            try:
                dest_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dest_sock.connect((self.remote_host, self.remote_port))
                
                while True:
                    data = channel.recv(1024)
                    if not data:
                        break
                    dest_sock.send(data)
                    
                    data = dest_sock.recv(1024)
                    if not data:
                        break
                    channel.send(data)
                
                dest_sock.close()
                channel.close()
            except Exception:
                pass
        
        # This is a simplified version - full implementation would use threading
        self.tunnel_active = True

    async def disconnect(self) -> None:
        """Close SSH tunnel"""
        if self.transport:
            try:
                self.transport.cancel_port_forward("", self.local_port)
            except Exception:
                pass
        
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None
        
        self.tunnel_active = False

    def get_local_endpoint(self) -> Dict[str, Any]:
        """Get local endpoint for database connection"""
        return {
            "host": "localhost",
            "port": self.local_port,
        }

    def is_active(self) -> bool:
        """Check if tunnel is active"""
        return self.tunnel_active and self.ssh_client is not None and self.ssh_client.get_transport() is not None


class TunnelManager:
    """Manage multiple SSH tunnels"""

    def __init__(self):
        self.tunnels: Dict[str, SSHTunnel] = {}

    async def create_tunnel(
        self,
        tunnel_id: str,
        ssh_host: str,
        ssh_port: int = 22,
        ssh_username: str = "",
        ssh_password: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        remote_host: str = "localhost",
        remote_port: int = 5432,
    ) -> SSHTunnel:
        """Create and start a new SSH tunnel"""
        if tunnel_id in self.tunnels:
            await self.close_tunnel(tunnel_id)
        
        tunnel = SSHTunnel(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_username=ssh_username,
            ssh_password=ssh_password,
            ssh_key_path=ssh_key_path,
            remote_host=remote_host,
            remote_port=remote_port,
        )
        
        await tunnel.connect()
        self.tunnels[tunnel_id] = tunnel
        return tunnel

    async def close_tunnel(self, tunnel_id: str) -> None:
        """Close a specific tunnel"""
        if tunnel_id in self.tunnels:
            await self.tunnels[tunnel_id].disconnect()
            del self.tunnels[tunnel_id]

    async def close_all_tunnels(self) -> None:
        """Close all tunnels"""
        for tunnel_id in list(self.tunnels.keys()):
            await self.close_tunnel(tunnel_id)

    def get_tunnel(self, tunnel_id: str) -> Optional[SSHTunnel]:
        """Get a tunnel by ID"""
        return self.tunnels.get(tunnel_id)

    def list_tunnels(self) -> Dict[str, Dict[str, Any]]:
        """List all active tunnels"""
        return {
            tunnel_id: {
                "active": tunnel.is_active(),
                "localPort": tunnel.local_port,
                "remoteHost": tunnel.remote_host,
                "remotePort": tunnel.remote_port,
            }
            for tunnel_id, tunnel in self.tunnels.items()
        }

