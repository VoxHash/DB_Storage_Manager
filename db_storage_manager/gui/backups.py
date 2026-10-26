"""
Backups management widget
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..backups.base import BackupInfo
from ..backups.local import LocalBackupAdapter
from ..backups.manager import BackupManager
from ..backups.protondrive import (
    ProtonDriveBackupAdapter,
    ProtonDriveNotConfiguredError,
    configuration_status as proton_drive_status,
)
from ..config import BACKUP_DIR
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from ..security.auth import PermissionDenied, get_auth_manager
from .utils import (
    apply_glassmorphism,
    apply_page_layout,
    configure_dense_table,
    make_page_header,
)

_STATUS_COLORS = {
    "pass": QColor(45, 140, 75),
    "fail": QColor(190, 55, 55),
    "missing_checksum": QColor(190, 140, 40),
    "not_found": QColor(190, 55, 55),
    "not_configured": QColor(190, 140, 40),
    "unknown": QColor(120, 120, 120),
    "idle": QColor(120, 120, 120),
}


class BackupsWidget(QWidget):
    """Backups management widget"""

    def __init__(self, connections, backup_dir=None):
        super().__init__()
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.backup_manager = BackupManager()
        self.backup_dir = backup_dir or BACKUP_DIR
        self._backups: List[BackupInfo] = []
        self._verify_results: Dict[str, Dict[str, Any]] = {}
        self._list_source = "local"
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)
        self.refresh_backups()
        self._refresh_proton_status()
        self.apply_rbac()

    def apply_rbac(self) -> None:
        auth = get_auth_manager()
        can_read = auth.has_permission("backups:read")
        can_create = auth.has_permission("backups:create")
        can_restore = auth.has_permission("backups:restore")
        self.refresh_button.setEnabled(can_read)
        self.refresh_proton_button.setEnabled(can_read)
        self.verify_selected_button.setEnabled(can_read)
        self.verify_all_button.setEnabled(can_read)
        self.dry_run_button.setEnabled(can_restore)
        self.create_button.setEnabled(can_create)

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        apply_page_layout(layout)
        t = self.i18n.translate

        layout.addWidget(
            make_page_header(
                t("tabs.backups"),
                t(
                    "backups.page_subtitle",
                    default="Create, verify, and restore local or Proton Drive backups",
                ),
            )
        )

        tabs = QTabWidget()
        layout.addWidget(tabs)

        create_widget = QWidget()
        create_layout = QVBoxLayout(create_widget)
        create_form = QFormLayout()
        self.connection_combo = QComboBox()
        self._reload_connection_combo()
        create_form.addRow(t("backups.connection"), self.connection_combo)

        self.adapter_combo = QComboBox()
        self.adapter_combo.addItem(t("backups.local"), "local")
        self.adapter_combo.addItem(t("backups.proton_drive"), "protondrive")
        self.adapter_combo.currentIndexChanged.connect(self._refresh_proton_status)
        create_form.addRow(t("backups.adapter"), self.adapter_combo)

        self.compression_combo = QComboBox()
        self.compression_combo.addItem(t("backups.none"), "none")
        self.compression_combo.addItem(t("backups.gzip"), "gzip")
        self.compression_combo.addItem(t("backups.zstd"), "zstd")
        create_form.addRow(t("backups.compression"), self.compression_combo)

        self.encrypt_checkbox = QCheckBox(t("backups.encryption"))
        self.encrypt_checkbox.setChecked(True)
        create_form.addRow("", self.encrypt_checkbox)

        self.encryption_key_edit = QLineEdit()
        self.encryption_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.encryption_key_edit.setPlaceholderText(
            t("backups.encryption_key_placeholder")
        )
        create_form.addRow(t("backups.encryption_key"), self.encryption_key_edit)
        create_layout.addLayout(create_form)

        self.proton_status_label = QLabel("")
        self.proton_status_label.setWordWrap(True)
        self.proton_status_label.setObjectName("backupProtonStatus")
        create_layout.addWidget(self.proton_status_label)

        create_actions = QHBoxLayout()
        self.create_button = QPushButton(t("backups.create"))
        self.create_button.setObjectName("PrimaryButton")
        self.create_button.clicked.connect(self.create_backup)
        create_actions.addWidget(self.create_button)
        create_actions.addStretch()
        create_layout.addLayout(create_actions)
        create_layout.addStretch()
        tabs.addTab(create_widget, t("backups.create_backup"))

        restore_widget = QWidget()
        restore_layout = QVBoxLayout(restore_widget)
        restore_layout.addWidget(QLabel(t("backups.restore_backup")))

        self.verify_status_label = QLabel(t("backups.verify_idle"))
        self.verify_status_label.setWordWrap(True)
        self.verify_status_label.setObjectName("backupVerifyStatus")
        restore_layout.addWidget(self.verify_status_label)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton(t("backups.refresh"))
        self.refresh_button.clicked.connect(self.refresh_backups)
        actions.addWidget(self.refresh_button)

        self.refresh_proton_button = QPushButton(t("backups.refresh_proton"))
        self.refresh_proton_button.clicked.connect(self.refresh_proton_backups)
        actions.addWidget(self.refresh_proton_button)

        self.verify_selected_button = QPushButton(t("backups.verify_checksum"))
        self.verify_selected_button.clicked.connect(self.verify_selected)
        actions.addWidget(self.verify_selected_button)

        self.verify_all_button = QPushButton(t("backups.verify_all"))
        self.verify_all_button.clicked.connect(self.verify_all)
        actions.addWidget(self.verify_all_button)

        self.dry_run_button = QPushButton(t("backups.dry_run_restore"))
        self.dry_run_button.clicked.connect(self.dry_run_selected)
        actions.addWidget(self.dry_run_button)
        actions.addStretch()
        restore_layout.addLayout(actions)

        self.backups_table = QTableWidget(0, 6)
        self.backups_table.setHorizontalHeaderLabels(
            [
                t("backups.col_name"),
                t("backups.col_size"),
                t("backups.col_created"),
                t("backups.col_sha256"),
                t("backups.col_status"),
                t("backups.col_detail"),
            ]
        )
        self.backups_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.backups_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.backups_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.backups_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_dense_table(self.backups_table)
        restore_layout.addWidget(self.backups_table)
        tabs.addTab(restore_widget, t("backups.restore_backup"))

        scheduled_widget = QWidget()
        scheduled_layout = QVBoxLayout(scheduled_widget)
        scheduled_layout.addWidget(QLabel(t("backups.scheduled_backups")))
        tabs.addTab(scheduled_widget, t("backups.scheduled_backups"))

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        self._reload_connection_combo()

    def _reload_connection_combo(self) -> None:
        current = self.connection_combo.currentData() if hasattr(self, "connection_combo") else None
        self.connection_combo.clear()
        for conn in self.connections or []:
            if isinstance(conn, ConnectionConfig):
                self.connection_combo.addItem(conn.name, conn)
            elif isinstance(conn, dict):
                name = str(conn.get("name") or conn.get("id") or "connection")
                self.connection_combo.addItem(name, conn)
        if current is not None:
            for idx in range(self.connection_combo.count()):
                if self.connection_combo.itemData(idx) == current:
                    self.connection_combo.setCurrentIndex(idx)
                    break

    def _adapter(self) -> LocalBackupAdapter:
        return LocalBackupAdapter(base_path=self.backup_dir)

    def _refresh_proton_status(self) -> None:
        t = self.i18n.translate
        status = proton_drive_status()
        if status.get("configured"):
            text = t(
                "backups.proton_ready",
                remote=status.get("remote"),
                path=status.get("remote_path"),
            )
            color = _STATUS_COLORS["pass"]
        else:
            text = t(
                "backups.proton_not_configured",
                error=status.get("error") or status.get("message") or "",
            )
            color = _STATUS_COLORS["not_configured"]
        self.proton_status_label.setText(text)
        self.proton_status_label.setStyleSheet(f"color: {color.name()};")

    def _as_connection_config(self, value: Any) -> Optional[ConnectionConfig]:
        if isinstance(value, ConnectionConfig):
            return value
        if isinstance(value, dict):
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
            payload = {k: value[k] for k in allowed if k in value}
            if not payload.get("id") or not payload.get("name") or not payload.get("type"):
                return None
            return ConnectionConfig(**payload)
        return None

    def create_backup(self) -> None:
        """Create a local or Proton Drive backup for the selected connection."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:create")
        except PermissionDenied as exc:
            self.proton_status_label.setText(str(exc))
            return

        connection = self._as_connection_config(self.connection_combo.currentData())
        if connection is None:
            self.proton_status_label.setText(t("backups.no_connection_selected"))
            return

        adapter_type = self.adapter_combo.currentData() or "local"
        compression = self.compression_combo.currentData() or "none"
        encrypt = self.encrypt_checkbox.isChecked()
        enc_key = self.encryption_key_edit.text().strip() or None
        if adapter_type == "protondrive" and encrypt and not enc_key:
            self.proton_status_label.setText(t("backups.encryption_key_required"))
            return

        options = {
            "compression": compression,
            "encryption": encrypt,
            "encryptionKey": enc_key,
            "adapterType": adapter_type,
        }
        try:
            if adapter_type == "protondrive":
                adapter = self.backup_manager.get_adapter("protondrive")
                if adapter is None:
                    raise ProtonDriveNotConfiguredError(
                        t("backups.proton_not_configured", error="adapter unavailable")
                    )
            else:
                adapter = self._adapter()
            info = asyncio.run(
                self.backup_manager.create_backup(adapter, connection, options)
            )
            self.proton_status_label.setText(
                t("backups.backup_created_detail", name=info.name, path=info.path)
            )
            if adapter_type == "protondrive":
                self.refresh_proton_backups()
            else:
                self.refresh_backups()
        except ProtonDriveNotConfiguredError as exc:
            self.proton_status_label.setText(
                t("backups.proton_not_configured", error=str(exc))
            )
        except Exception as exc:
            self.proton_status_label.setText(
                t("backups.backup_failed_detail", error=str(exc))
            )

    def refresh_backups(self) -> None:
        """Reload local backups into the table."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        self._list_source = "local"
        try:
            self._backups = asyncio.run(self._adapter().list_backups())
        except Exception as exc:
            self._backups = []
            self._set_status(
                t("backups.refresh_failed", error=str(exc)),
                "fail",
            )
            self._populate_table()
            return

        self._verify_results.clear()
        self._populate_table()
        self._set_status(
            t("backups.verify_idle_count", count=len(self._backups)),
            "idle",
        )

    def refresh_proton_backups(self) -> None:
        """List backups from Proton Drive when credentials/rclone are available."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        self._list_source = "protondrive"
        try:
            adapter = self.backup_manager.get_adapter("protondrive")
            if adapter is None:
                raise ProtonDriveNotConfiguredError("Proton Drive adapter unavailable")
            self._backups = asyncio.run(adapter.list_backups())
        except ProtonDriveNotConfiguredError as exc:
            self._backups = []
            self._set_status(
                t("backups.proton_not_configured", error=str(exc)),
                "not_configured",
            )
            self._populate_table()
            return
        except Exception as exc:
            self._backups = []
            self._set_status(
                t("backups.refresh_failed", error=str(exc)),
                "fail",
            )
            self._populate_table()
            return

        self._verify_results.clear()
        self._populate_table()
        self._set_status(
            t("backups.proton_listed", count=len(self._backups)),
            "idle",
        )

    def _populate_table(self) -> None:
        t = self.i18n.translate
        selected_id = None
        current = self._selected_backup()
        if current is not None:
            selected_id = current.id

        self.backups_table.setRowCount(0)
        restore_row = None
        for backup in self._backups:
            row = self.backups_table.rowCount()
            self.backups_table.insertRow(row)
            if selected_id is not None and backup.id == selected_id:
                restore_row = row
            sha = (backup.metadata or {}).get("sha256") or ""
            sha_short = f"{sha[:12]}…" if len(sha) > 12 else (sha or "—")
            created = backup.createdAt
            if isinstance(created, datetime):
                created_text = created.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_text = str(created)

            result = self._verify_results.get(backup.id) or self._verify_results.get(
                backup.path
            )
            if result:
                status = str(
                    result.get("status") or ("pass" if result.get("ok") else "fail")
                )
                detail = result.get("error") or result.get("stage") or ""
                if result.get("ok") and result.get("integrity"):
                    detail = f"integrity={result['integrity']}"
                elif result.get("ok"):
                    detail = t("backups.status_pass")
            else:
                status = "unknown"
                detail = t("backups.status_unchecked")

            values = [
                backup.name,
                self._format_size(backup.size),
                created_text,
                sha_short,
                status.upper(),
                str(detail),
            ]
            color = _STATUS_COLORS.get(status, _STATUS_COLORS["unknown"])
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, backup.id)
                if col in (4, 5):
                    item.setForeground(QBrush(color))
                self.backups_table.setItem(row, col, item)

        if restore_row is not None:
            self.backups_table.selectRow(restore_row)

    def _selected_backup(self) -> Optional[BackupInfo]:
        rows = self.backups_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self.backups_table.item(row, 0)
        if item is None:
            return None
        backup_id = item.data(Qt.ItemDataRole.UserRole)
        return next((b for b in self._backups if b.id == backup_id), None)

    def verify_selected(self) -> None:
        """Verify SHA-256 for the selected backup."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backup = self._selected_backup()
        if backup is None:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return

        if self._list_source == "protondrive" or (
            backup.metadata or {}
        ).get("destination") == "protondrive":
            adapter = self.backup_manager.get_adapter("protondrive")
            if isinstance(adapter, ProtonDriveBackupAdapter):
                result = adapter.verify_remote_checksum(backup)
            else:
                result = {
                    "ok": False,
                    "status": "not_configured",
                    "error": "Proton Drive adapter unavailable",
                }
        else:
            result = self.backup_manager.verify_backup_checksum(backup)
        self._verify_results[backup.id] = result
        self._verify_results[backup.path] = result
        self._populate_table()
        self._present_checksum_result(result, single=True)

    def verify_all(self) -> None:
        """Verify SHA-256 for every listed backup via parallel helpers."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        if not self._backups:
            self._set_status(t("backups.no_backups"), "missing_checksum")
            return

        results = self.backup_manager.verify_backups_parallel(self._backups)
        by_id = {r.get("id"): r for r in results}
        for backup in self._backups:
            result = by_id.get(backup.id) or {
                "ok": False,
                "status": "not_found",
                "error": "Verification result missing",
            }
            self._verify_results[backup.id] = result
            self._verify_results[backup.path] = result
        self._populate_table()

        passed = sum(1 for r in results if r.get("ok"))
        failed = len(results) - passed
        if failed == 0:
            self._set_status(
                t("backups.verify_all_pass", count=passed),
                "pass",
            )
        else:
            self._set_status(
                t(
                    "backups.verify_all_fail",
                    passed=passed,
                    failed=failed,
                    total=len(results),
                ),
                "fail",
            )

    def dry_run_selected(self) -> None:
        """Checksum + payload dry-run restore for the selected backup."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:restore")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backup = self._selected_backup()
        if backup is None:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return

        local_info = backup
        temp_download: Optional[Path] = None
        try:
            if self._list_source == "protondrive" or (
                backup.metadata or {}
            ).get("destination") == "protondrive":
                adapter = self.backup_manager.get_adapter("protondrive")
                if not isinstance(adapter, ProtonDriveBackupAdapter):
                    self._set_status(
                        t(
                            "backups.proton_not_configured",
                            error="adapter unavailable",
                        ),
                        "not_configured",
                    )
                    return
                temp_download = Path(asyncio.run(adapter.restore_backup(backup)))
                local_info = BackupInfo(
                    id=backup.id,
                    name=backup.name,
                    path=str(temp_download),
                    size=backup.size,
                    createdAt=backup.createdAt,
                    status=backup.status,
                    metadata=dict(backup.metadata or {}),
                )
            result = self.backup_manager.dry_run_restore(local_info)
        finally:
            if temp_download is not None:
                temp_download.unlink(missing_ok=True)

        self._verify_results[backup.id] = result
        self._verify_results[backup.path] = result
        self._populate_table()
        if result.get("ok"):
            integrity = result.get("integrity")
            detail = (
                t("backups.dry_run_pass_integrity", integrity=integrity)
                if integrity
                else t("backups.dry_run_pass")
            )
            self._set_status(detail, "pass")
        else:
            stage = result.get("stage") or "dry_run"
            error = result.get("error") or t("backups.dry_run_failed")
            self._set_status(
                t("backups.dry_run_fail", stage=stage, error=error),
                str(result.get("status") or "fail"),
            )

    def _present_checksum_result(
        self, result: Dict[str, Any], *, single: bool = False
    ) -> None:
        t = self.i18n.translate
        status = str(result.get("status") or ("pass" if result.get("ok") else "fail"))
        if result.get("ok"):
            self._set_status(t("backups.verify_pass"), "pass")
            return
        if status == "missing_checksum":
            self._set_status(t("backups.verify_missing_checksum"), "missing_checksum")
            return
        if status == "not_found":
            self._set_status(t("backups.verify_not_found"), "not_found")
            return
        if status == "not_configured":
            self._set_status(
                t(
                    "backups.proton_not_configured",
                    error=result.get("error") or "",
                ),
                "not_configured",
            )
            return
        expected = result.get("expected") or "—"
        actual = result.get("actual") or "—"
        self._set_status(
            t("backups.verify_fail", expected=expected, actual=actual),
            "fail",
        )

    def _set_status(self, text: str, status: str) -> None:
        color = _STATUS_COLORS.get(status, _STATUS_COLORS["unknown"])
        self.verify_status_label.setText(text)
        self.verify_status_label.setStyleSheet(
            f"color: {color.name()}; font-weight: 600;"
        )

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{int(value)} B" if unit == "B" else f"{value:.2f} {unit}"
            value /= 1024
        return f"{size} B"
