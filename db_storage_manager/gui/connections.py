"""
Connections management widget
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QMessageBox,
    QGroupBox,
    QCheckBox,
    QFileDialog,
    QLabel,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
import uuid

from ..db.factory import DatabaseConnectionFactory
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from ..security.auth import PermissionDenied, get_auth_manager
from ..ssh import (
    SSHTunnelError,
    TunnelManager,
    normalize_ssh_config,
    validate_ssh_config,
)
from .utils import apply_glassmorphism


def _connection_config_kwargs(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a connection dict to ConnectionConfig fields."""
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


class ConnectionDialog(QDialog):
    """Dialog for adding/editing connections"""

    def __init__(self, connection=None, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(
            t("connections.add_dialog_title")
            if not connection
            else t("connections.edit_dialog_title")
        )
        self.setModal(True)
        self.setMinimumWidth(480)
        self.init_ui()
        apply_glassmorphism(self)

    def init_ui(self):
        """Initialize UI"""
        layout = QFormLayout(self)
        t = self.i18n.translate

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My Database")
        layout.addRow(f"{t('connections.name')}", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(
            [
                "postgresql",
                "mysql",
                "sqlite",
                "mongodb",
                "redis",
                "oracle",
                "sqlserver",
                "clickhouse",
                "influxdb",
            ]
        )
        layout.addRow(f"{t('connections.type')}", self.type_combo)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        layout.addRow(f"{t('connections.host')}", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5432)
        layout.addRow(f"{t('connections.port')}", self.port_spin)

        self.database_edit = QLineEdit()
        layout.addRow(f"{t('connections.database')}", self.database_edit)

        self.username_edit = QLineEdit()
        layout.addRow(f"{t('connections.username')}", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(f"{t('connections.password')}", self.password_edit)

        # SSH tunnel group
        self.ssh_group = QGroupBox(t("ssh.tunnel", "SSH Tunnel"))
        ssh_layout = QFormLayout(self.ssh_group)

        self.ssh_enabled = QCheckBox(t("ssh.enable", "Use SSH tunnel via bastion"))
        self.ssh_enabled.toggled.connect(self._on_ssh_toggled)
        ssh_layout.addRow(self.ssh_enabled)

        self.ssh_host_edit = QLineEdit()
        self.ssh_host_edit.setPlaceholderText("bastion.example.com")
        ssh_layout.addRow(t("ssh.ssh_host", "SSH Host:"), self.ssh_host_edit)

        self.ssh_port_spin = QSpinBox()
        self.ssh_port_spin.setRange(1, 65535)
        self.ssh_port_spin.setValue(22)
        ssh_layout.addRow(t("ssh.ssh_port", "SSH Port:"), self.ssh_port_spin)

        self.ssh_username_edit = QLineEdit()
        ssh_layout.addRow(t("ssh.ssh_username", "SSH Username:"), self.ssh_username_edit)

        self.ssh_password_edit = QLineEdit()
        self.ssh_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_password_edit.setPlaceholderText(
            t("ssh.password_or_passphrase", "Password or key passphrase")
        )
        ssh_layout.addRow(t("ssh.ssh_password", "SSH Password:"), self.ssh_password_edit)

        key_row = QHBoxLayout()
        self.ssh_key_edit = QLineEdit()
        self.ssh_key_edit.setPlaceholderText("~/.ssh/id_ed25519")
        browse_btn = QPushButton(t("ssh.browse_key", "Browse…"))
        browse_btn.clicked.connect(self._browse_ssh_key)
        key_row.addWidget(self.ssh_key_edit)
        key_row.addWidget(browse_btn)
        ssh_layout.addRow(t("ssh.ssh_key_path", "SSH Key Path:"), key_row)

        self.ssh_remote_host_edit = QLineEdit()
        self.ssh_remote_host_edit.setPlaceholderText("localhost")
        self.ssh_remote_host_edit.setToolTip(
            t(
                "ssh.remote_host_hint",
                "Database host as reachable from the bastion (often localhost)",
            )
        )
        ssh_layout.addRow(t("ssh.remote_host", "Remote Host:"), self.ssh_remote_host_edit)

        self.ssh_remote_port_spin = QSpinBox()
        self.ssh_remote_port_spin.setRange(1, 65535)
        self.ssh_remote_port_spin.setValue(5432)
        ssh_layout.addRow(t("ssh.remote_port", "Remote Port:"), self.ssh_remote_port_spin)

        layout.addRow(self.ssh_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # Load connection data if editing
        if self.connection:
            self.name_edit.setText(self.connection.get("name", ""))
            index = self.type_combo.findText(self.connection.get("type", "postgresql"))
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.host_edit.setText(self.connection.get("host", ""))
            self.port_spin.setValue(self.connection.get("port", 5432) or 5432)
            self.database_edit.setText(self.connection.get("database", ""))
            self.username_edit.setText(self.connection.get("username", ""))
            self.password_edit.setText(self.connection.get("password", ""))

            ssh = normalize_ssh_config(self.connection.get("ssh_config"))
            self.ssh_enabled.setChecked(bool(ssh.get("enabled")))
            self.ssh_host_edit.setText(ssh.get("ssh_host") or "")
            self.ssh_port_spin.setValue(int(ssh.get("ssh_port") or 22))
            self.ssh_username_edit.setText(ssh.get("ssh_username") or "")
            self.ssh_password_edit.setText(ssh.get("ssh_password") or "")
            self.ssh_key_edit.setText(ssh.get("ssh_key_path") or "")
            self.ssh_remote_host_edit.setText(ssh.get("remote_host") or "localhost")
            self.ssh_remote_port_spin.setValue(int(ssh.get("remote_port") or 5432))
        else:
            self.ssh_remote_host_edit.setText("localhost")
            self.ssh_remote_port_spin.setValue(self.port_spin.value())

        self._on_ssh_toggled(self.ssh_enabled.isChecked())

    def _on_ssh_toggled(self, enabled: bool) -> None:
        for widget in (
            self.ssh_host_edit,
            self.ssh_port_spin,
            self.ssh_username_edit,
            self.ssh_password_edit,
            self.ssh_key_edit,
            self.ssh_remote_host_edit,
            self.ssh_remote_port_spin,
        ):
            widget.setEnabled(enabled)

    def _browse_ssh_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.i18n.translate("ssh.browse_key_title", "Select SSH private key"),
            "",
            "Private keys (*);;All files (*)",
        )
        if path:
            self.ssh_key_edit.setText(path)

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(
                self,
                self.i18n.translate("common.error"),
                self.i18n.translate("ssh.name_required", "Connection name is required"),
            )
            return
        if self.ssh_enabled.isChecked():
            try:
                validate_ssh_config(self._ssh_config_from_form())
            except SSHTunnelError as exc:
                QMessageBox.warning(
                    self,
                    self.i18n.translate("common.error"),
                    str(exc),
                )
                return
        self.accept()

    def _ssh_config_from_form(self) -> Dict[str, Any]:
        return normalize_ssh_config(
            {
                "enabled": self.ssh_enabled.isChecked(),
                "ssh_host": self.ssh_host_edit.text(),
                "ssh_port": self.ssh_port_spin.value(),
                "ssh_username": self.ssh_username_edit.text(),
                "ssh_password": self.ssh_password_edit.text(),
                "ssh_key_path": self.ssh_key_edit.text(),
                "remote_host": self.ssh_remote_host_edit.text() or "localhost",
                "remote_port": self.ssh_remote_port_spin.value(),
            }
        )

    def get_connection(self):
        """Get connection data from form"""
        ssh_config = self._ssh_config_from_form()
        if not ssh_config["enabled"]:
            ssh_config = None
        return {
            "id": self.connection.get("id") if self.connection else str(uuid.uuid4()),
            "name": self.name_edit.text().strip(),
            "type": self.type_combo.currentText(),
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
            "ssh_config": ssh_config,
        }


class ConnectionsWidget(QWidget):
    """Connections management widget"""

    connection_added = pyqtSignal(dict)
    connection_updated = pyqtSignal(dict)
    connection_deleted = pyqtSignal(str)

    def __init__(self, connections: Optional[List[Dict[str, Any]]] = None):
        super().__init__()
        self.connections: List[Dict[str, Any]] = list(connections or [])
        self.tunnel_manager = TunnelManager()
        self.i18n = get_i18n_manager()
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)
        self._update_table()
        self.apply_rbac()

    def apply_rbac(self) -> None:
        """Gate mutation buttons by RBAC permissions."""
        auth = get_auth_manager()
        self.add_button.setEnabled(auth.has_permission("connections:write"))
        # edit/delete/test still depend on selection; re-evaluate
        self._on_selection_changed()

    def set_connections(self, connections: List[Dict[str, Any]]) -> None:
        """Replace the in-memory connection list (e.g. after SecureStore load)."""
        self.connections = list(connections or [])
        self._update_table()
        self._refresh_tunnel_controls()

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        t = self.i18n.translate

        # Buttons
        button_layout = QHBoxLayout()
        self.add_button = QPushButton(t("connections.add_connection"))
        self.add_button.clicked.connect(self._add_connection)
        button_layout.addWidget(self.add_button)

        self.edit_button = QPushButton(t("connections.edit"))
        self.edit_button.clicked.connect(self._edit_connection)
        self.edit_button.setEnabled(False)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton(t("connections.delete"))
        self.delete_button.clicked.connect(self._delete_connection)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        self.test_button = QPushButton(t("connections.test_connection"))
        self.test_button.clicked.connect(self._test_connection)
        self.test_button.setEnabled(False)
        button_layout.addWidget(self.test_button)

        self.open_tunnel_button = QPushButton(t("ssh.create_tunnel", "Open Tunnel"))
        self.open_tunnel_button.clicked.connect(self._open_tunnel)
        self.open_tunnel_button.setEnabled(False)
        button_layout.addWidget(self.open_tunnel_button)

        self.close_tunnel_button = QPushButton(t("ssh.close_tunnel", "Close Tunnel"))
        self.close_tunnel_button.clicked.connect(self._close_tunnel)
        self.close_tunnel_button.setEnabled(False)
        button_layout.addWidget(self.close_tunnel_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.tunnel_status_label = QLabel(t("ssh.tunnel_inactive", "Tunnel Inactive"))
        self.tunnel_status_label.setWordWrap(True)
        self.tunnel_status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.tunnel_status_label)

        # Connections table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                t("connections.name").rstrip(":"),
                t("connections.type").rstrip(":"),
                t("connections.host").rstrip(":"),
                t("connections.database").rstrip(":"),
                t("ssh.tunnel", "SSH Tunnel"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

    def _selected_row(self) -> int:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return -1
        return indexes[0].row()

    def _on_selection_changed(self):
        """Handle table selection change"""
        has_selection = self._selected_row() >= 0
        auth = get_auth_manager()
        self.edit_button.setEnabled(
            has_selection and auth.has_permission("connections:write")
        )
        self.delete_button.setEnabled(
            has_selection and auth.has_permission("connections:delete")
        )
        self.test_button.setEnabled(
            has_selection and auth.has_permission("connections:read")
        )
        self._refresh_tunnel_controls()

    def _deny(self, exc: PermissionDenied) -> None:
        t = self.i18n.translate
        QMessageBox.warning(
            self,
            t("auth.denied", default="Access denied"),
            str(exc),
        )

    def _ssh_enabled_for(self, connection: Dict[str, Any]) -> bool:
        ssh = connection.get("ssh_config") or {}
        return bool(ssh.get("enabled"))

    def _refresh_tunnel_controls(self) -> None:
        t = self.i18n.translate
        row = self._selected_row()
        if row < 0 or row >= len(self.connections):
            self.open_tunnel_button.setEnabled(False)
            self.close_tunnel_button.setEnabled(False)
            self.tunnel_status_label.setText(t("ssh.tunnel_inactive", "Tunnel Inactive"))
            return

        connection = self.connections[row]
        ssh_on = self._ssh_enabled_for(connection)
        tunnel = self.tunnel_manager.get_tunnel(connection["id"])
        active = tunnel is not None and tunnel.is_active()

        self.open_tunnel_button.setEnabled(ssh_on and not active)
        self.close_tunnel_button.setEnabled(active)

        if active and tunnel is not None:
            endpoint = tunnel.get_local_endpoint()
            self.tunnel_status_label.setText(
                t(
                    "ssh.tunnel_active_detail",
                    "Tunnel active → {host}:{port} (bastion {bastion})",
                ).format(
                    host=endpoint["host"],
                    port=endpoint["port"],
                    bastion=tunnel.ssh_host,
                )
            )
        elif ssh_on:
            self.tunnel_status_label.setText(
                t("ssh.tunnel_ready", "SSH configured — open tunnel before connecting remotely")
            )
        else:
            self.tunnel_status_label.setText(t("ssh.tunnel_inactive", "Tunnel Inactive"))

    def _add_connection(self):
        """Add a new connection"""
        try:
            get_auth_manager().require("connections:write")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        dialog = ConnectionDialog(parent=self)
        if dialog.exec():
            connection = dialog.get_connection()
            self.connections.append(connection)
            self._update_table()
            self.connection_added.emit(connection)

    def _edit_connection(self):
        """Edit selected connection"""
        try:
            get_auth_manager().require("connections:write")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        row = self._selected_row()
        if row < 0:
            return

        connection = self.connections[row]
        dialog = ConnectionDialog(connection, parent=self)
        if dialog.exec():
            updated = dialog.get_connection()
            # Closing an old tunnel if SSH settings changed
            old_tunnel = self.tunnel_manager.get_tunnel(connection["id"])
            if old_tunnel is not None:
                self.tunnel_manager.close_tunnel_sync(connection["id"])
            self.connections[row] = updated
            self._update_table()
            self.connection_updated.emit(updated)
            self._refresh_tunnel_controls()

    def _delete_connection(self):
        """Delete selected connection"""
        try:
            get_auth_manager().require("connections:delete")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        row = self._selected_row()
        if row < 0:
            return

        t = self.i18n.translate
        reply = QMessageBox.question(
            self,
            t("common.confirm"),
            t("connections.delete_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            connection_id = self.connections[row]["id"]
            if self.tunnel_manager.get_tunnel(connection_id):
                self.tunnel_manager.close_tunnel_sync(connection_id)
            del self.connections[row]
            self._update_table()
            self.connection_deleted.emit(connection_id)
            self._refresh_tunnel_controls()

    def _open_tunnel(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        connection = self.connections[row]
        ssh_config = connection.get("ssh_config") or {}
        t = self.i18n.translate
        try:
            validate_ssh_config(ssh_config)
            tunnel = self.tunnel_manager.create_tunnel_sync(
                connection["id"],
                ssh_config=ssh_config,
            )
            endpoint = tunnel.get_local_endpoint()
            self._refresh_tunnel_controls()
            self._update_table()
            QMessageBox.information(
                self,
                t("common.success"),
                t(
                    "ssh.tunnel_opened",
                    "SSH tunnel open on {host}:{port}",
                ).format(host=endpoint["host"], port=endpoint["port"]),
            )
        except SSHTunnelError as exc:
            self._refresh_tunnel_controls()
            QMessageBox.critical(
                self,
                t("common.error"),
                f"{t('ssh.tunnel_failed', 'Failed to open SSH tunnel')}:\n{exc}",
            )
        except Exception as exc:
            self._refresh_tunnel_controls()
            QMessageBox.critical(
                self,
                t("common.error"),
                f"{t('ssh.tunnel_failed', 'Failed to open SSH tunnel')}:\n{exc}",
            )

    def _close_tunnel(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        connection = self.connections[row]
        t = self.i18n.translate
        self.tunnel_manager.close_tunnel_sync(connection["id"])
        self._refresh_tunnel_controls()
        self._update_table()
        QMessageBox.information(
            self,
            t("common.success"),
            t("ssh.tunnel_closed", "SSH tunnel closed"),
        )

    def _ensure_tunnel_for_test(self, connection: Dict[str, Any]) -> Dict[str, Any]:
        """Return connection kwargs pointed at the local tunnel endpoint when SSH is on."""
        ssh_config = connection.get("ssh_config") or {}
        if not ssh_config.get("enabled"):
            return _connection_config_kwargs(connection)

        tunnel = self.tunnel_manager.get_tunnel(connection["id"])
        if tunnel is None or not tunnel.is_active():
            tunnel = self.tunnel_manager.create_tunnel_sync(
                connection["id"],
                ssh_config=ssh_config,
            )
        endpoint = tunnel.get_local_endpoint()
        kwargs = _connection_config_kwargs(connection)
        kwargs["host"] = endpoint["host"]
        kwargs["port"] = endpoint["port"]
        # Already forwarded; do not pass ssh_config into the driver layer
        kwargs["ssh_config"] = None
        return kwargs

    def _test_connection(self):
        """Test selected connection"""
        row = self._selected_row()
        if row < 0:
            return

        connection = self.connections[row]
        t = self.i18n.translate
        try:
            config_kwargs = self._ensure_tunnel_for_test(connection)
            self._refresh_tunnel_controls()
            self._update_table()
            config = ConnectionConfig(**config_kwargs)

            async def _probe() -> bool:
                db = await DatabaseConnectionFactory.acquire(config)
                try:
                    return bool(db.connected)
                finally:
                    await DatabaseConnectionFactory.release(db)

            result = asyncio.run(_probe())

            if result:
                QMessageBox.information(
                    self, t("common.success"), t("connections.test_success")
                )
            else:
                QMessageBox.warning(
                    self, t("common.error"), t("connections.test_failed")
                )
        except SSHTunnelError as exc:
            self._refresh_tunnel_controls()
            QMessageBox.critical(
                self,
                t("common.error"),
                f"{t('ssh.tunnel_failed', 'Failed to open SSH tunnel')}:\n{exc}",
            )
        except Exception as e:
            self._refresh_tunnel_controls()
            QMessageBox.critical(
                self, t("common.error"), f"{t('errors.connection_failed')}:\n{str(e)}"
            )

    def close_all_tunnels(self) -> None:
        """Called by MainWindow on shutdown."""
        self.tunnel_manager.close_all_tunnels_sync()

    def _tunnel_status_text(self, connection: Dict[str, Any]) -> str:
        t = self.i18n.translate
        if not self._ssh_enabled_for(connection):
            return "—"
        tunnel = self.tunnel_manager.get_tunnel(connection["id"])
        if tunnel is not None and tunnel.is_active():
            endpoint = tunnel.get_local_endpoint()
            return t("ssh.tunnel_active", "Tunnel Active") + f" (:{endpoint['port']})"
        return t("ssh.tunnel_inactive", "Tunnel Inactive")

    def _update_table(self):
        """Update connections table"""
        self.table.setRowCount(len(self.connections))
        for row, conn in enumerate(self.connections):
            self.table.setItem(row, 0, QTableWidgetItem(conn.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(conn.get("type", "")))
            self.table.setItem(row, 2, QTableWidgetItem(conn.get("host", "") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(conn.get("database", "") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(self._tunnel_status_text(conn)))
