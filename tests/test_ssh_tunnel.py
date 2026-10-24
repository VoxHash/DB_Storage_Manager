"""SSH tunnel helpers — validation, SecureStore persistence, mocked Paramiko."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from db_storage_manager.ssh import (
    SSHTunnel,
    SSHTunnelError,
    TunnelManager,
    format_ssh_error,
    normalize_ssh_config,
    validate_ssh_config,
)


def _enabled_cfg(**overrides):
    base = {
        "enabled": True,
        "ssh_host": "bastion.example.com",
        "ssh_port": 22,
        "ssh_username": "deploy",
        "ssh_password": "secret",
        "ssh_key_path": None,
        "remote_host": "localhost",
        "remote_port": 5432,
    }
    base.update(overrides)
    return base


def test_normalize_ssh_config_defaults_and_stripping():
    cfg = normalize_ssh_config(
        {
            "enabled": 1,
            "ssh_host": "  bastion  ",
            "ssh_username": " alice ",
            "ssh_password": "",
            "ssh_key_path": "  ",
            "remote_host": "",
        }
    )
    assert cfg["enabled"] is True
    assert cfg["ssh_host"] == "bastion"
    assert cfg["ssh_username"] == "alice"
    assert cfg["ssh_password"] is None
    assert cfg["ssh_key_path"] is None
    assert cfg["remote_host"] == "localhost"
    assert cfg["ssh_port"] == 22


def test_validate_ssh_config_requires_auth(tmp_path):
    with pytest.raises(SSHTunnelError, match="not enabled"):
        validate_ssh_config({"enabled": False})

    with pytest.raises(SSHTunnelError, match="bastion host"):
        validate_ssh_config(_enabled_cfg(ssh_host=""))

    with pytest.raises(SSHTunnelError, match="username"):
        validate_ssh_config(_enabled_cfg(ssh_username=""))

    with pytest.raises(SSHTunnelError, match="private key path or an SSH password"):
        validate_ssh_config(_enabled_cfg(ssh_password=None, ssh_key_path=None))

    missing = tmp_path / "no-such-key"
    with pytest.raises(SSHTunnelError, match="not found"):
        validate_ssh_config(
            _enabled_cfg(ssh_password=None, ssh_key_path=str(missing))
        )

    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    validate_ssh_config(_enabled_cfg(ssh_password=None, ssh_key_path=str(key)))


def test_format_ssh_error_maps_common_failures():
    assert "authentication failed" in format_ssh_error(
        Exception("Authentication failed.")
    ).lower()
    assert "timed out" in format_ssh_error(TimeoutError("timed out")).lower()
    assert "refused" in format_ssh_error(OSError("Connection refused")).lower()


def test_find_free_port_is_bindable():
    port = SSHTunnel._find_free_port()
    assert 1 <= port <= 65535
    # Port should be free enough to bind again after finder closed its socket
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        assert sock.getsockname()[1] >= 1


def test_get_local_endpoint_and_inactive_status():
    tunnel = SSHTunnel(
        ssh_host="bastion.example.com",
        ssh_username="deploy",
        ssh_password="x",
        local_port=34567,
    )
    assert tunnel.get_local_endpoint() == {"host": "127.0.0.1", "port": 34567}
    assert tunnel.is_active() is False
    status = tunnel.status()
    assert status["active"] is False
    assert status["localPort"] == 34567
    assert status["sshHost"] == "bastion.example.com"


def test_connect_sync_success_with_mocked_paramiko():
    mock_transport = MagicMock()
    mock_transport.is_active.return_value = True

    mock_client = MagicMock()
    mock_client.get_transport.return_value = mock_transport

    with patch("db_storage_manager.ssh.tunnel.SSHClient", return_value=mock_client):
        tunnel = SSHTunnel(
            ssh_host="bastion.example.com",
            ssh_port=22,
            ssh_username="deploy",
            ssh_password="secret",
            remote_host="db.internal",
            remote_port=5432,
        )
        tunnel.connect_sync()
        assert tunnel.tunnel_active is True
        assert tunnel.is_active() is True
        mock_client.connect.assert_called_once()
        kwargs = mock_client.connect.call_args.kwargs
        assert kwargs["hostname"] == "bastion.example.com"
        assert kwargs["username"] == "deploy"
        assert kwargs["password"] == "secret"
        endpoint = tunnel.get_local_endpoint()
        assert endpoint["host"] == "127.0.0.1"
        assert 1 <= endpoint["port"] <= 65535

        tunnel.disconnect_sync()
        assert tunnel.is_active() is False
        mock_client.close.assert_called()


def test_connect_sync_key_auth(tmp_path):
    key = tmp_path / "id_rsa"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")

    mock_transport = MagicMock()
    mock_transport.is_active.return_value = True
    mock_client = MagicMock()
    mock_client.get_transport.return_value = mock_transport

    with patch("db_storage_manager.ssh.tunnel.SSHClient", return_value=mock_client):
        tunnel = SSHTunnel.from_ssh_config(
            _enabled_cfg(
                ssh_password="passphrase",
                ssh_key_path=str(key),
            )
        )
        tunnel.connect_sync()
        kwargs = mock_client.connect.call_args.kwargs
        assert kwargs["key_filename"] == str(key)
        assert kwargs["passphrase"] == "passphrase"
        tunnel.disconnect_sync()


def test_connect_sync_maps_paramiko_errors():
    mock_client = MagicMock()
    mock_client.connect.side_effect = OSError("Connection refused")

    with patch("db_storage_manager.ssh.tunnel.SSHClient", return_value=mock_client):
        tunnel = SSHTunnel(
            ssh_host="bastion.example.com",
            ssh_username="deploy",
            ssh_password="secret",
        )
        with pytest.raises(SSHTunnelError, match="refused"):
            tunnel.connect_sync()
        assert tunnel.is_active() is False
        assert tunnel.last_error is not None
        assert "refused" in tunnel.last_error.lower()


def test_tunnel_manager_create_close_with_ssh_config():
    mock_transport = MagicMock()
    mock_transport.is_active.return_value = True
    mock_client = MagicMock()
    mock_client.get_transport.return_value = mock_transport

    manager = TunnelManager()
    with patch("db_storage_manager.ssh.tunnel.SSHClient", return_value=mock_client):
        tunnel = manager.create_tunnel_sync(
            "conn-1",
            ssh_config=_enabled_cfg(),
        )
        assert manager.get_tunnel("conn-1") is tunnel
        listed = manager.list_tunnels()
        assert "conn-1" in listed
        assert listed["conn-1"]["active"] is True

        manager.close_tunnel_sync("conn-1")
        assert manager.get_tunnel("conn-1") is None

        # Recreate then close_all
        manager.create_tunnel_sync("conn-2", ssh_config=_enabled_cfg())
        manager.close_all_tunnels_sync()
        assert manager.list_tunnels() == {}


def test_secure_store_ssh_settings_upsert_and_remove(isolated_secure_store):
    store, _ = isolated_secure_store
    connection = {
        "id": "c-ssh-1",
        "name": "Prod via bastion",
        "type": "postgresql",
        "host": "db.internal",
        "port": 5432,
        "database": "app",
        "username": "dbuser",
        "password": "dbpass",
        "ssh_config": _enabled_cfg(ssh_key_path="/home/user/.ssh/id_ed25519"),
    }
    store.save_connections([connection])
    store.upsert_ssh_settings_for_connection(connection)

    loaded = store.get_connections()
    assert loaded[0]["ssh_config"]["ssh_host"] == "bastion.example.com"
    assert loaded[0]["ssh_config"]["ssh_password"] == "secret"

    keys = store.get_ssh_keys()
    assert len(keys) == 1
    assert keys[0]["connection_id"] == "c-ssh-1"
    assert keys[0]["ssh_host"] == "bastion.example.com"
    assert keys[0]["ssh_key_path"] == "/home/user/.ssh/id_ed25519"
    assert keys[0]["has_password"] is True
    # Password must not be mirrored into ssh-keys inventory
    assert "ssh_password" not in keys[0]
    assert "secret" not in str(keys[0])

    # Update upserts in place
    connection["ssh_config"]["ssh_host"] = "bastion-2.example.com"
    store.upsert_ssh_settings_for_connection(connection)
    keys = store.get_ssh_keys()
    assert len(keys) == 1
    assert keys[0]["ssh_host"] == "bastion-2.example.com"

    store.remove_ssh_settings_for_connection("c-ssh-1")
    assert store.get_ssh_keys() == []


def test_secure_store_skips_upsert_when_ssh_disabled(isolated_secure_store):
    store, _ = isolated_secure_store
    connection = {
        "id": "c-plain",
        "name": "Local",
        "ssh_config": {"enabled": False},
    }
    store.upsert_ssh_settings_for_connection(connection)
    assert store.get_ssh_keys() == []
