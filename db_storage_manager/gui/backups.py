"""
Backups management widget
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from ..config import BACKUP_DIR
from ..i18n.manager import get_i18n_manager
from .utils import apply_glassmorphism

_STATUS_COLORS = {
    "pass": QColor(45, 140, 75),
    "fail": QColor(190, 55, 55),
    "missing_checksum": QColor(190, 140, 40),
    "not_found": QColor(190, 55, 55),
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
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)
        self.refresh_backups()

    def init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        t = self.i18n.translate

        tabs = QTabWidget()
        layout.addWidget(tabs)

        create_widget = QWidget()
        create_layout = QVBoxLayout(create_widget)
        create_layout.addWidget(QLabel(t("backups.create_backup")))
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
        restore_layout.addWidget(self.backups_table)
        tabs.addTab(restore_widget, t("backups.restore_backup"))

        scheduled_widget = QWidget()
        scheduled_layout = QVBoxLayout(scheduled_widget)
        scheduled_layout.addWidget(QLabel(t("backups.scheduled_backups")))
        tabs.addTab(scheduled_widget, t("backups.scheduled_backups"))

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections

    def _adapter(self) -> LocalBackupAdapter:
        return LocalBackupAdapter(base_path=self.backup_dir)

    def refresh_backups(self) -> None:
        """Reload local backups into the table."""
        t = self.i18n.translate
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
        backup = self._selected_backup()
        if backup is None:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return

        result = self.backup_manager.verify_backup_checksum(backup)
        self._verify_results[backup.id] = result
        self._verify_results[backup.path] = result
        self._populate_table()
        self._present_checksum_result(result, single=True)

    def verify_all(self) -> None:
        """Verify SHA-256 for every listed backup via parallel helpers."""
        t = self.i18n.translate
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
        backup = self._selected_backup()
        if backup is None:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return

        result = self.backup_manager.dry_run_restore(backup)
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
