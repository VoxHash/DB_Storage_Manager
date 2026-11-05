"""
Backups management widget
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import QCoreApplication, QItemSelectionModel, QSize, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..audit import write_audit
from ..backups.base import BackupInfo
from ..backups.local import LocalBackupAdapter, resolve_local_backup_dir
from ..backups.manager import ENCRYPTED_ADAPTERS, BackupManager
from ..backups.protondrive import (
    ProtonDriveNotConfiguredError,
    configuration_status as proton_drive_status,
)
from ..backups.s3 import S3NotConfiguredError
from ..backups.s3 import configuration_status as s3_status
from ..backups.scheduler import ScheduledBackupManager
from ..db.base import ConnectionConfig
from ..experimental import is_restore_enabled
from ..i18n.manager import get_i18n_manager
from ..security.auth import PermissionDenied, get_auth_manager
from .icons import set_icon_only
from .jobs import JobRunner, JobWorker
from .restore_dialog import RestoreBatchDialog, RestoreDialog
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
    "restoring": QColor(70, 120, 190),
}


# Backwards-compatible name (tests / callers import ``BackupJobWorker``).
BackupJobWorker = JobWorker


class _WrappingLabel(QLabel):
    """Word-wrapped label whose height follows its width.

    A plain ``QLabel`` reports a one-line minimum height. The restore size
    explainer then paints over the table header when the row is narrower
    than the sentence.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        margins = self.contentsMargins()
        inner = max(1, width - margins.left() - margins.right())
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        rect = self.fontMetrics().boundingRect(0, 0, inner, 10_000, flags, self.text())
        return rect.height() + margins.top() + margins.bottom() + 4

    def sizeHint(self) -> QSize:
        width = self.width() if self.width() > 40 else 480
        return QSize(max(width, 0), self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        width = self.width() if self.width() > 40 else 320
        return QSize(0, self.heightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.updateGeometry()


# Independent job groups: one active job per group, groups run concurrently.
_GROUP_CREATE = "create"
_GROUP_LIST = "list"
_GROUP_VERIFY = "verify"
_GROUP_RESTORE = "restore"
_GROUP_DELETE = "delete"


class BackupsWidget(QWidget):
    """Backups management widget"""

    def __init__(self, connections, backup_dir=None):
        super().__init__()
        self.connections = connections
        self.i18n = get_i18n_manager()
        self.backup_manager = BackupManager()
        self.schedule_manager = ScheduledBackupManager()
        self._backup_dir_explicit = backup_dir is not None
        self.backup_dir = Path(backup_dir) if backup_dir is not None else resolve_local_backup_dir()
        self._backups: List[BackupInfo] = []
        self._verify_results: Dict[str, Dict[str, Any]] = {}
        # Per-backup Status/Detail that must survive a list reload.
        self._row_outcomes: Dict[str, Dict[str, str]] = {}
        # Passphrases that opened a backup in this process. Not written to disk.
        self._session_passphrases: Dict[str, str] = {}
        self._restore_busy_targets: Set[str] = set()
        self._restore_wait: Dict[str, List[Tuple[BackupInfo, Dict[str, Any]]]] = {}
        self._list_source = "local"
        self._jobs = JobRunner(self)
        self._jobs.state_changed.connect(self._refresh_job_buttons)
        self.setObjectName("glassmorphism")
        self.init_ui()
        apply_glassmorphism(self)
        self._refresh_backups_sync()
        self._on_adapter_changed()
        self._reload_schedules_table()
        self.apply_rbac()
        # Scheduler thread is idle until at least one enabled schedule exists.
        if any(s.enabled for s in self.schedule_manager.get_schedules()):
            self.schedule_manager.start()

    def apply_rbac(self) -> None:
        self._refresh_job_buttons()

    def _refresh_job_buttons(self) -> None:
        """Enable controls from RBAC permissions minus groups with a running job."""
        if not hasattr(self, "create_button"):
            return
        auth = get_auth_manager()
        can_read = auth.has_permission("backups:read")
        can_create = auth.has_permission("backups:create")
        busy_create = self._jobs.is_busy(_GROUP_CREATE)
        busy_list = self._jobs.is_busy(_GROUP_LIST)
        self.create_button.setEnabled(can_create and not busy_create)
        self.refresh_button.setEnabled(can_read and not busy_list)
        self.refresh_proton_button.setEnabled(can_read and not busy_list)
        self.refresh_s3_button.setEnabled(can_read and not busy_list)
        # Verify, dry-run, restore, and delete live on the row menu. Their
        # enabled state is decided when the menu opens (one job per backup).
        can_settings = auth.has_permission("settings:write")
        for name in ("configure_proton_button", "configure_s3_button"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(
                    can_settings or not auth.is_rbac_active()
                )
        if hasattr(self, "schedule_add_button"):
            self.schedule_add_button.setEnabled(can_create)
            self.schedule_remove_button.setEnabled(can_create)
            self.schedule_toggle_button.setEnabled(can_create)
            self.schedule_refresh_button.setEnabled(can_read)

    def wait_idle(self, timeout_ms: int = 10000) -> None:
        """Pump the event loop until every background job finished (tests / shutdown)."""
        import time

        deadline = time.monotonic() + timeout_ms / 1000.0
        while self._jobs.any_busy() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        self._jobs.wait_all(1000)
        QCoreApplication.processEvents()

    def status_summary(self) -> str:
        """One-line backups status for the system tray menu."""
        t = self.i18n.translate
        schedules = self.schedule_manager.get_schedules()
        enabled = sum(1 for s in schedules if s.enabled)
        state = (
            t("tray.backups_job_running")
            if self._jobs.any_busy()
            else t("tray.backups_job_idle")
        )
        return t(
            "tray.backups_status",
            enabled=enabled,
            total=len(schedules),
            state=state,
        )

    def shutdown(self) -> None:
        """Stop the scheduler thread and wait briefly for running jobs."""
        try:
            self.schedule_manager.stop()
        finally:
            self._jobs.wait_all(3000)

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
                    default="Create, verify, and restore local, Proton Drive or S3 backups",
                ),
            )
        )

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        create_widget = QWidget()
        create_layout = QVBoxLayout(create_widget)
        create_form = QFormLayout()
        self.connection_combo = QComboBox()
        self._reload_connection_combo()
        create_form.addRow(t("backups.connection"), self.connection_combo)

        self.adapter_combo = QComboBox()
        self.adapter_combo.addItem(t("backups.local"), "local")
        self.adapter_combo.addItem(t("backups.proton_drive"), "protondrive")
        self.adapter_combo.addItem(
            t("settings.adapter_s3", default="S3-compatible"), "s3"
        )
        self.adapter_combo.currentIndexChanged.connect(self._on_adapter_changed)
        create_form.addRow(t("backups.adapter"), self.adapter_combo)

        self.compression_combo = QComboBox()
        self.compression_combo.addItem(t("backups.none"), "none")
        self.compression_combo.addItem(t("backups.gzip"), "gzip")
        self.compression_combo.addItem(t("backups.zstd"), "zstd")
        create_form.addRow(t("backups.compression"), self.compression_combo)

        self.encrypt_checkbox = QCheckBox(t("backups.encryption"))
        self.encrypt_checkbox.setChecked(True)
        self.encrypt_checkbox.setToolTip(
            t(
                "backups.encryption_tooltip",
                default="Enterprise default: encrypt before upload (DSMENC1). "
                "Required for Proton Drive and S3 backups.",
            )
        )
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
        self.configure_proton_button = QPushButton(
            t("backups.configure_proton", default="Configure Proton Drive…")
        )
        self.configure_proton_button.clicked.connect(self._configure_proton_drive)
        create_actions.addWidget(self.configure_proton_button)
        self.configure_s3_button = QPushButton(
            t("settings.configure_s3", default="Configure S3…")
        )
        self.configure_s3_button.clicked.connect(self._configure_s3)
        create_actions.addWidget(self.configure_s3_button)
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
        self._restore_actions = actions
        self.refresh_button = QPushButton(t("backups.refresh"))
        self.refresh_button.clicked.connect(
            lambda _checked=False: self.refresh_backups(queue=True)
        )
        actions.addWidget(self.refresh_button)

        self.refresh_proton_button = QPushButton(t("backups.refresh_proton"))
        self.refresh_proton_button.clicked.connect(
            lambda _checked=False: self.refresh_proton_backups(queue=True)
        )
        actions.addWidget(self.refresh_proton_button)

        self.refresh_s3_button = QPushButton(
            t("backups.refresh_s3", default="Refresh S3")
        )
        self.refresh_s3_button.clicked.connect(
            lambda _checked=False: self.refresh_remote_backups("s3", queue=True)
        )
        actions.addWidget(self.refresh_s3_button)
        actions.addStretch()
        restore_layout.addLayout(actions)

        self.size_explainer_label = _WrappingLabel(
            t(
                "backups.size_explainer",
                default=(
                    "Size is the stored file after compression and encryption. "
                    "“Source DB size” is the live on-disk size when the backup "
                    "ran (tables + indexes + TOAST). A dump holds only logical "
                    "data, so a backup is normally much smaller than the "
                    "Dashboard’s Total size."
                ),
            )
        )
        self.size_explainer_label.setObjectName("backupSizeExplainer")
        restore_layout.addWidget(self.size_explainer_label)
        restore_layout.addSpacing(8)

        self.backups_table = QTableWidget(0, 7)
        self.backups_table.setHorizontalHeaderLabels(
            [
                t("backups.col_name"),
                t("backups.col_size"),
                t("backups.col_source_size", default="Source DB size"),
                t("backups.col_created"),
                t("backups.col_sha256"),
                t("backups.col_status"),
                t("backups.col_detail"),
            ]
        )
        # Name keeps the leftover width and elides in the middle so the
        # timestamp suffix stays visible. Created and the short columns
        # size to their text instead of sharing that width equally.
        backup_header = self.backups_table.horizontalHeader()
        backup_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        backup_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        backup_header.setStretchLastSection(False)
        backup_header.setMinimumSectionSize(72)
        self.backups_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.backups_table.setHorizontalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel
        )
        self.backups_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.backups_table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self.backups_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.backups_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.backups_table.customContextMenuRequested.connect(
            self._backup_context_menu
        )
        configure_dense_table(self.backups_table)
        restore_layout.addWidget(self.backups_table, 1)
        tabs.addTab(restore_widget, t("backups.restore_backup"))

        scheduled_widget = QWidget()
        scheduled_layout = QVBoxLayout(scheduled_widget)
        scheduled_layout.addWidget(
            QLabel(
                t(
                    "backups.scheduled_help",
                    default="Schedule recurring dumps.",
                )
            )
        )
        schedule_form = QFormLayout()
        self.schedule_name_edit = QLineEdit()
        self.schedule_name_edit.setPlaceholderText(
            t("backups.schedule_name_placeholder", default="Nightly production dump")
        )
        schedule_form.addRow(
            t("backups.schedule_name", default="Name"), self.schedule_name_edit
        )
        self.schedule_connection_combo = QComboBox()
        schedule_form.addRow(
            t("backups.connection"), self.schedule_connection_combo
        )
        # The Create-tab combo is filled before this one exists; fill both now.
        self._reload_connection_combo()
        self.schedule_adapter_combo = QComboBox()
        self.schedule_adapter_combo.addItem(t("backups.local"), "local")
        self.schedule_adapter_combo.addItem(t("backups.proton_drive"), "protondrive")
        self.schedule_adapter_combo.addItem(
            t("settings.adapter_s3", default="S3-compatible"), "s3"
        )
        schedule_form.addRow(t("backups.adapter"), self.schedule_adapter_combo)
        self.schedule_interval_spin = QSpinBox()
        self.schedule_interval_spin.setRange(5, 10080)
        self.schedule_interval_spin.setValue(1440)
        self.schedule_interval_spin.setSuffix(
            t("backups.schedule_minutes_suffix", default=" min")
        )
        schedule_form.addRow(
            t("backups.schedule_interval", default="Interval"),
            self.schedule_interval_spin,
        )
        self.schedule_encrypt_checkbox = QCheckBox(t("backups.encryption"))
        self.schedule_encrypt_checkbox.setChecked(True)
        schedule_form.addRow("", self.schedule_encrypt_checkbox)
        self.schedule_passphrase_edit = QLineEdit()
        self.schedule_passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.schedule_passphrase_edit.setPlaceholderText(
            t("backups.encryption_key_placeholder")
        )
        schedule_form.addRow(
            t("backups.encryption_key"), self.schedule_passphrase_edit
        )
        scheduled_layout.addLayout(schedule_form)

        schedule_actions = QHBoxLayout()
        self.schedule_add_button = QPushButton(
            t("backups.schedule_add", default="Add schedule")
        )
        self.schedule_add_button.setObjectName("PrimaryButton")
        self.schedule_add_button.clicked.connect(self._add_schedule)
        schedule_actions.addWidget(self.schedule_add_button)
        self.schedule_toggle_button = QPushButton(
            t("backups.schedule_toggle", default="Enable / Disable")
        )
        self.schedule_toggle_button.clicked.connect(self._toggle_selected_schedule)
        schedule_actions.addWidget(self.schedule_toggle_button)
        self.schedule_remove_button = QPushButton(
            t("backups.schedule_remove", default="Remove")
        )
        self.schedule_remove_button.clicked.connect(self._remove_selected_schedule)
        schedule_actions.addWidget(self.schedule_remove_button)
        self.schedule_refresh_button = QPushButton(
            t("backups.schedule_refresh", default="Refresh schedules")
        )
        set_icon_only(
            self.schedule_refresh_button,
            "refresh",
            t("backups.schedule_refresh", default="Refresh schedules"),
        )
        self.schedule_refresh_button.clicked.connect(self._reload_schedules_table)
        schedule_actions.addWidget(self.schedule_refresh_button)
        schedule_actions.addStretch()
        scheduled_layout.addLayout(schedule_actions)

        self.schedules_table = QTableWidget(0, 6)
        self.schedules_table.setHorizontalHeaderLabels(
            [
                t("backups.schedule_col_name", default="Name"),
                t("backups.schedule_col_connection", default="Connection"),
                t("backups.schedule_col_adapter", default="Adapter"),
                t("backups.schedule_col_interval", default="Interval"),
                t("backups.schedule_col_enabled", default="Enabled"),
                t("backups.schedule_col_last", default="Last run"),
            ]
        )
        self.schedules_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.schedules_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.schedules_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.schedules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_dense_table(self.schedules_table)
        scheduled_layout.addWidget(self.schedules_table, 1)
        tabs.addTab(scheduled_widget, t("backups.scheduled_backups"))

    def update_connections(self, connections):
        """Update connections list"""
        self.connections = connections
        self._reload_connection_combo()

    def _reload_connection_combo(self) -> None:
        current = (
            self.connection_combo.currentData()
            if hasattr(self, "connection_combo")
            else None
        )
        schedule_current = (
            self.schedule_connection_combo.currentData()
            if hasattr(self, "schedule_connection_combo")
            else None
        )
        combos = [self.connection_combo]
        if hasattr(self, "schedule_connection_combo"):
            combos.append(self.schedule_connection_combo)
        for combo in combos:
            combo.clear()
            for conn in self.connections or []:
                if isinstance(conn, ConnectionConfig):
                    combo.addItem(conn.name, conn)
                elif isinstance(conn, dict):
                    name = str(conn.get("name") or conn.get("id") or "connection")
                    combo.addItem(name, conn)
        if current is not None:
            for idx in range(self.connection_combo.count()):
                if self.connection_combo.itemData(idx) == current:
                    self.connection_combo.setCurrentIndex(idx)
                    break
        if schedule_current is not None and hasattr(self, "schedule_connection_combo"):
            for idx in range(self.schedule_connection_combo.count()):
                if self.schedule_connection_combo.itemData(idx) == schedule_current:
                    self.schedule_connection_combo.setCurrentIndex(idx)
                    break

    def _adapter(self) -> LocalBackupAdapter:
        return LocalBackupAdapter(base_path=self.backup_dir)

    def _selected_adapter_type(self) -> str:
        return str(self.adapter_combo.currentData() or "local")

    def _configure_proton_drive(self) -> None:
        """Open SecureStore Proton Drive credential dialog and refresh status."""
        from .proton_drive_config import open_proton_drive_config

        if open_proton_drive_config(self):
            self._refresh_proton_status()

    def _configure_s3(self) -> None:
        """Open the SecureStore S3 dialog and refresh status."""
        from .s3_config import open_s3_config

        if open_s3_config(self):
            self._refresh_proton_status()

    def refresh_destinations(self) -> None:
        """Re-evaluate destination status, the local directory, and buttons."""
        self._apply_configured_backup_dir()
        self._refresh_proton_status()
        self._refresh_job_buttons()

    def _apply_configured_backup_dir(self) -> None:
        """Follow Settings → local backup directory unless the caller overrode it."""
        if self._backup_dir_explicit:
            return
        new_dir = resolve_local_backup_dir()
        if Path(new_dir) == Path(self.backup_dir):
            return
        self.backup_dir = new_dir
        if self._list_source == "local":
            self.refresh_backups(queue=True)

    def _on_adapter_changed(self) -> None:
        """Off-machine backups must encrypt at rest before upload (opsec)."""
        if self._selected_adapter_type() in ENCRYPTED_ADAPTERS:
            self.encrypt_checkbox.setChecked(True)
            self.encrypt_checkbox.setEnabled(False)
        else:
            self.encrypt_checkbox.setEnabled(True)
        self._refresh_proton_status()

    def _announce(self, message: str, *, create_tab: bool) -> None:
        if create_tab:
            self.proton_status_label.setText(message)
            self.proton_status_label.setStyleSheet("")
        else:
            self._set_status(message, "idle")

    def _run_backup_job(
        self,
        job: Callable[[], Any],
        *,
        group: str,
        busy_message: str,
        on_ok: Callable[[Any], None],
        create_tab: bool = False,
        on_fail: Optional[Callable[[str], None]] = None,
        queue: bool = False,
        announce: bool = True,
    ) -> bool:
        """Run ``job`` on a worker thread; other groups keep running concurrently.

        ``announce=False`` leaves the current status line alone (a restore
        outcome must stay visible while the backup list reloads).
        """

        def _fail(message: str) -> None:
            if on_fail is not None:
                on_fail(message)
            elif create_tab:
                self.proton_status_label.setText(
                    self.i18n.translate("backups.backup_failed_detail", error=message)
                )
            else:
                self._set_status(
                    self.i18n.translate("backups.refresh_failed", error=message),
                    "fail",
                )

        started = self._jobs.submit(
            group,
            job,
            on_ok,
            _fail,
            on_start=(
                (lambda: self._announce(busy_message, create_tab=create_tab))
                if announce
                else None
            ),
            queue=queue,
        )
        if not started and announce:
            self._announce(
                self.i18n.translate(
                    "backups.job_in_progress",
                    default="A backup job is already running. Wait for it to finish.",
                ),
                create_tab=create_tab,
            )
        return started

    def _refresh_proton_status(self) -> None:
        """Show Proton Drive readiness only when that adapter is selected.

        Local create/restore must not surface rclone/Proton configuration errors.
        """
        adapter_type = self._selected_adapter_type()
        if hasattr(self, "configure_proton_button"):
            self.configure_proton_button.setVisible(adapter_type == "protondrive")
        if hasattr(self, "configure_s3_button"):
            self.configure_s3_button.setVisible(adapter_type == "s3")

        t = self.i18n.translate
        if adapter_type == "s3":
            status = s3_status()
            if status.get("configured"):
                text = t(
                    "backups.s3_ready",
                    default="S3 ready: bucket {bucket} ({credentials}).",
                    bucket=status.get("bucket"),
                    credentials=status.get("credentials"),
                )
                color = _STATUS_COLORS["pass"]
            else:
                text = t(
                    "backups.s3_not_configured",
                    default="S3 is not configured: {error}",
                    error=status.get("error") or "",
                )
                color = _STATUS_COLORS["not_configured"]
            self.proton_status_label.setText(text)
            self.proton_status_label.setStyleSheet(f"color: {color.name()};")
            return

        if adapter_type != "protondrive":
            self.proton_status_label.clear()
            self.proton_status_label.setStyleSheet("")
            return

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
        # Opsec: off-machine uploads are always DSMENC1-encrypted first.
        encrypt = (
            True
            if adapter_type in ENCRYPTED_ADAPTERS
            else self.encrypt_checkbox.isChecked()
        )
        enc_key = self.encryption_key_edit.text().strip() or None
        if encrypt and not enc_key:
            self.proton_status_label.setText(t("backups.encryption_key_required"))
            return

        options = {
            "compression": compression,
            "encryption": encrypt,
            "encryptionKey": enc_key,
            "adapterType": adapter_type,
        }
        manager = self.backup_manager
        local_dir = self.backup_dir

        def job() -> BackupInfo:
            if adapter_type == "protondrive":
                adapter = manager.get_adapter("protondrive")
                if adapter is None:
                    raise ProtonDriveNotConfiguredError(
                        "Proton Drive adapter unavailable"
                    )
            elif adapter_type == "s3":
                adapter = manager.get_adapter("s3")
                if adapter is None:
                    raise S3NotConfiguredError("S3 adapter unavailable")
            else:
                adapter = LocalBackupAdapter(base_path=local_dir)
            return asyncio.run(
                manager.create_backup(adapter, connection, options)
            )

        def on_ok(info: BackupInfo) -> None:
            self._remember_passphrase(info, enc_key)
            self.proton_status_label.setText(
                t("backups.backup_created_detail", name=info.name, path=info.path)
            )
            if adapter_type in ("protondrive", "s3"):
                self.refresh_remote_backups(adapter_type, queue=True)
            else:
                self.refresh_backups(queue=True)

        def on_fail(message: str) -> None:
            if "not configured" in message.lower() or "unavailable" in message.lower():
                self.proton_status_label.setText(
                    t(
                        "backups.s3_not_configured",
                        default="S3 is not configured: {error}",
                        error=message,
                    )
                    if adapter_type == "s3"
                    else t("backups.proton_not_configured", error=message)
                )
            else:
                self.proton_status_label.setText(
                    t("backups.backup_failed_detail", error=message)
                )

        self._run_backup_job(
            job,
            group=_GROUP_CREATE,
            busy_message=t("backups.create_in_progress", default="Creating backup…"),
            on_ok=on_ok,
            on_fail=on_fail,
            create_tab=True,
        )

    def _refresh_backups_sync(self) -> None:
        """Local FS list used only during widget construction (no event loop yet)."""
        t = self.i18n.translate
        self._list_source = "local"
        try:
            self._backups = asyncio.run(self._adapter().list_backups())
            self._verify_results.clear()
            self._populate_table()
            self._set_status(
                t("backups.verify_idle_count", count=len(self._backups)),
                "idle",
            )
        except Exception as exc:
            self._backups = []
            self._populate_table()
            self._set_status(t("backups.refresh_failed", error=str(exc)), "fail")

    def refresh_backups(self, *, queue: bool = False, keep_status: bool = False) -> None:
        """Reload local backups into the table (off the GUI thread).

        ``keep_status`` reloads the table without replacing the line a restore
        just wrote (success, skipped ACLs, or a failure).
        """
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            if not keep_status:
                self._set_status(str(exc), "fail")
            return
        self._list_source = "local"
        local_dir = self.backup_dir

        def job() -> List[BackupInfo]:
            return asyncio.run(LocalBackupAdapter(base_path=local_dir).list_backups())

        def on_ok(backups: List[BackupInfo]) -> None:
            self._backups = backups
            self._verify_results.clear()
            self._populate_table()
            if keep_status:
                return
            self._set_status(
                t("backups.verify_idle_count", count=len(self._backups)),
                "idle",
            )

        def on_fail(message: str) -> None:
            detail = self._status_detail(message, "unknown error")
            failed = t(
                "backups.refresh_failed",
                default="Failed to refresh backups: {error}",
                error=detail,
            )
            current = self.verify_status_label.text().strip()
            self._set_status(f"{current} {failed}".strip() or failed, "fail")

        self._run_backup_job(
            job,
            group=_GROUP_LIST,
            busy_message=t(
                "backups.refresh_in_progress",
                default="Refreshing local backups…",
            ),
            on_ok=on_ok,
            on_fail=on_fail if keep_status else None,
            queue=queue,
            announce=not keep_status,
        )

    def refresh_proton_backups(self, *, queue: bool = False) -> None:
        """List backups from Proton Drive when credentials/rclone are available."""
        self.refresh_remote_backups("protondrive", queue=queue)

    def refresh_remote_backups(self, destination: str, *, queue: bool = False) -> None:
        """List backups from an off-machine destination (``protondrive`` / ``s3``)."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        self._list_source = destination
        manager = self.backup_manager
        is_s3 = destination == "s3"

        def job() -> List[BackupInfo]:
            adapter = manager.get_adapter(destination)
            if adapter is None:
                raise (
                    S3NotConfiguredError("S3 adapter unavailable")
                    if is_s3
                    else ProtonDriveNotConfiguredError(
                        "Proton Drive adapter unavailable"
                    )
                )
            return asyncio.run(adapter.list_backups())

        def on_ok(backups: List[BackupInfo]) -> None:
            self._backups = backups
            self._verify_results.clear()
            self._populate_table()
            self._set_status(
                t(
                    "backups.s3_listed",
                    default="{count} S3 backup(s) listed.",
                    count=len(self._backups),
                )
                if is_s3
                else t("backups.proton_listed", count=len(self._backups)),
                "idle",
            )

        def on_fail(message: str) -> None:
            self._backups = []
            self._populate_table()
            if "not configured" in message.lower() or "unavailable" in message.lower():
                self._set_status(
                    t(
                        "backups.s3_not_configured",
                        default="S3 is not configured: {error}",
                        error=message,
                    )
                    if is_s3
                    else t("backups.proton_not_configured", error=message),
                    "not_configured",
                )
            else:
                self._set_status(
                    t("backups.refresh_failed", error=message),
                    "fail",
                )

        self._run_backup_job(
            job,
            group=_GROUP_LIST,
            busy_message=(
                t("backups.s3_refresh_in_progress", default="Listing S3 backups…")
                if is_s3
                else t(
                    "backups.proton_refresh_in_progress",
                    default="Listing Proton Drive backups…",
                )
            ),
            on_ok=on_ok,
            on_fail=on_fail,
            queue=queue,
        )

    def _populate_table(self) -> None:
        t = self.i18n.translate
        selected_ids: Set[str] = set()
        selection = self.backups_table.selectionModel()
        if selection is not None:
            for index in selection.selectedRows():
                item = self.backups_table.item(index.row(), 0)
                if item is not None:
                    backup_id = item.data(Qt.ItemDataRole.UserRole)
                    if backup_id:
                        selected_ids.add(str(backup_id))

        self.backups_table.setRowCount(0)
        for backup in self._backups:
            row = self.backups_table.rowCount()
            self.backups_table.insertRow(row)
            sha = (backup.metadata or {}).get("sha256") or ""
            sha_short = f"{sha[:12]}…" if len(sha) > 12 else (sha or "—")
            created = backup.createdAt
            if isinstance(created, datetime):
                created_text = created.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_text = str(created)

            outcome = self._row_outcomes.get(backup.id)
            result = self._verify_results.get(backup.id) or self._verify_results.get(
                backup.path
            )
            if outcome:
                code = outcome.get("code") or "unknown"
                status_text = outcome.get("status") or code
                detail = outcome.get("detail") or ""
            elif result:
                code = str(
                    result.get("status") or ("pass" if result.get("ok") else "fail")
                )
                detail = result.get("error") or result.get("stage") or ""
                if result.get("ok") and result.get("integrity"):
                    detail = f"integrity={result['integrity']}"
                elif result.get("ok"):
                    detail = t("backups.status_pass")
                status_text = code.upper()
            else:
                code = "unknown"
                status_text = "UNKNOWN"
                detail = t("backups.status_unchecked")

            meta = backup.metadata or {}
            live_bytes = self._meta_bytes(meta.get("sourceStorageBytes"))
            values = [
                backup.name,
                self._format_size(backup.size),
                self._format_size(live_bytes) if live_bytes is not None else "—",
                created_text,
                sha_short,
                status_text,
                str(detail),
            ]
            color = _STATUS_COLORS.get(code, _STATUS_COLORS["unknown"])
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, backup.id)
                if col in (5, 6):
                    item.setForeground(QBrush(color))
                if col == 0:
                    item.setToolTip(str(value))
                elif col == 3:
                    item.setToolTip(created_text)
                elif col in (1, 2):
                    item.setToolTip(self._size_tooltip(backup))
                self.backups_table.setItem(row, col, item)

        if selected_ids:
            flags = (
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows
            )
            model = self.backups_table.selectionModel()
            for row in range(self.backups_table.rowCount()):
                item = self.backups_table.item(row, 0)
                if item is None:
                    continue
                if str(item.data(Qt.ItemDataRole.UserRole) or "") not in selected_ids:
                    continue
                model.select(self.backups_table.model().index(row, 0), flags)

    @staticmethod
    def _meta_bytes(value: Any) -> Optional[int]:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    def _size_tooltip(self, backup: BackupInfo) -> str:
        """Explain why a backup is smaller than the live database size."""
        t = self.i18n.translate
        meta = backup.metadata or {}
        stored = self._format_size(backup.size)
        dump = self._meta_bytes(meta.get("dumpSize"))
        live = self._meta_bytes(meta.get("sourceStorageBytes"))
        pipeline = []
        compression = str(meta.get("compression") or "none").lower()
        if compression != "none":
            pipeline.append(compression)
        if meta.get("encryption"):
            pipeline.append("AES-256-GCM")
        lines = [
            t(
                "backups.size_tip_stored",
                default="Stored file: {size} ({format}).",
                size=stored,
                format="+".join(pipeline)
                or t("backups.size_tip_raw", default="raw dump"),
            )
        ]
        if dump is not None:
            lines.append(
                t(
                    "backups.size_tip_dump",
                    default="Dump before compression/encryption: {size}.",
                    size=self._format_size(dump),
                )
            )
        if live is not None:
            lines.append(
                t(
                    "backups.size_tip_live",
                    default="Live database when the backup ran: {size} (tables, indexes, TOAST).",
                    size=self._format_size(live),
                )
            )
        else:
            lines.append(
                t(
                    "backups.size_tip_legacy",
                    default="No live size was recorded for this backup (created by an older version).",
                )
            )
        lines.append(
            t(
                "backups.size_tip_why",
                default="A dump stores logical data only; indexes, free space and bloat are not exported, so it is normally smaller than the Dashboard’s Total size.",
            )
        )
        return "\n".join(lines)

    def _selected_backups(self) -> List[BackupInfo]:
        rows = self.backups_table.selectionModel().selectedRows()
        found: List[BackupInfo] = []
        seen: Set[str] = set()
        for index in sorted(rows, key=lambda item: item.row()):
            cell = self.backups_table.item(index.row(), 0)
            if cell is None:
                continue
            backup_id = cell.data(Qt.ItemDataRole.UserRole)
            backup = next((b for b in self._backups if b.id == backup_id), None)
            if backup is None or backup.id in seen:
                continue
            seen.add(backup.id)
            found.append(backup)
        return found

    def _selected_backup(self) -> Optional[BackupInfo]:
        found = self._selected_backups()
        return found[0] if found else None

    def menu_action_enabled(self, kind: str) -> bool:
        """RBAC gate for a backup-table context action."""
        auth = get_auth_manager()
        if kind in ("verify", "verify_all"):
            return auth.has_permission("backups:read")
        if kind == "dry_run":
            return auth.has_permission("backups:restore")
        if kind == "restore":
            return is_restore_enabled() and auth.has_permission("backups:restore")
        if kind == "delete":
            return (
                auth.has_permission("backups:create")
                and not self._jobs.is_busy(_GROUP_LIST)
            )
        return False

    def context_menu_entries(self, count: int) -> List[Tuple[str, str, bool]]:
        """Actions for ``count`` selected backups: ``(kind, label, enabled)``."""
        t = self.i18n.translate
        if count < 1:
            return []
        entries: List[Tuple[str, str, bool]] = []
        if count == 1:
            entries.append(
                (
                    "verify",
                    t("backups.verify_checksum"),
                    self.menu_action_enabled("verify"),
                )
            )
        else:
            entries.append(
                (
                    "verify",
                    t(
                        "backups.verify_n",
                        default="Verify {count} backups",
                        count=count,
                    ),
                    self.menu_action_enabled("verify"),
                )
            )
        entries.append(
            (
                "verify_all",
                t("backups.verify_all"),
                self.menu_action_enabled("verify_all"),
            )
        )
        if count == 1:
            entries.append(
                (
                    "dry_run",
                    t("backups.dry_run_restore"),
                    self.menu_action_enabled("dry_run"),
                )
            )
            if is_restore_enabled():
                entries.append(
                    (
                        "restore",
                        t("backups.restore_full", default="Restore…"),
                        self.menu_action_enabled("restore"),
                    )
                )
            entries.append(
                (
                    "delete",
                    t("backups.delete", default="Delete…"),
                    self.menu_action_enabled("delete"),
                )
            )
        else:
            entries.append(
                (
                    "dry_run",
                    t(
                        "backups.dry_run_n",
                        default="Dry-run {count} backups",
                        count=count,
                    ),
                    self.menu_action_enabled("dry_run"),
                )
            )
            if is_restore_enabled():
                entries.append(
                    (
                        "restore",
                        t(
                            "backups.restore_n",
                            default="Restore {count} backups…",
                            count=count,
                        ),
                        self.menu_action_enabled("restore"),
                    )
                )
            entries.append(
                (
                    "delete",
                    t(
                        "backups.delete_n",
                        default="Delete {count} backups…",
                        count=count,
                    ),
                    self.menu_action_enabled("delete"),
                )
            )
        return entries

    def _backup_context_menu(self, pos) -> None:
        index = self.backups_table.indexAt(pos)
        if not index.isValid():
            return
        selected_rows = {
            item.row() for item in self.backups_table.selectionModel().selectedRows()
        }
        if index.row() not in selected_rows:
            self.backups_table.selectRow(index.row())
        backups = self._selected_backups()
        if not backups:
            return
        menu = QMenu(self)
        actions = {}
        for kind, label, enabled in self.context_menu_entries(len(backups)):
            action = menu.addAction(label)
            action.setEnabled(enabled)
            actions[action] = kind
        chosen = menu.exec(self.backups_table.viewport().mapToGlobal(pos))
        kind = actions.get(chosen)
        if kind == "verify":
            self.verify_selected()
        elif kind == "verify_all":
            self.verify_all()
        elif kind == "dry_run":
            self.dry_run_selected()
        elif kind == "restore":
            self.restore_selected()
        elif kind == "delete":
            self.delete_selected()

    def _set_row_outcome(
        self, backup_id: str, code: str, status: str, detail: str
    ) -> None:
        """Paint Status and Detail for one backup. Survives a list reload."""
        if not backup_id:
            return
        self._row_outcomes[backup_id] = {
            "code": code,
            "status": status,
            "detail": detail,
        }
        self._populate_table()

    def _remember_passphrase(
        self,
        backup: Optional[BackupInfo],
        passphrase: Optional[str],
        *,
        name: Optional[str] = None,
    ) -> None:
        """Keep a passphrase that opened a backup. Memory only, never disk."""
        if not passphrase:
            return
        if backup is not None:
            self._session_passphrases[backup.id] = passphrase
            if backup.name:
                self._session_passphrases["name:" + backup.name] = passphrase
        if name:
            self._session_passphrases["name:" + name] = passphrase

    def _known_passphrase(self, backup: BackupInfo) -> str:
        return (
            self._session_passphrases.get(backup.id)
            or self._session_passphrases.get("name:" + backup.name)
            or self.encryption_key_edit.text().strip()
        )

    def _passphrase_candidates(self, backup: BackupInfo) -> List[str]:
        """Keys to try, session key first, then the create-tab field."""
        if not (backup.metadata or {}).get("encryption"):
            return []
        found: List[str] = []
        for key in (backup.id, "name:" + backup.name):
            value = self._session_passphrases.get(key)
            if value and value not in found:
                found.append(value)
        typed = self.encryption_key_edit.text().strip()
        if typed and typed not in found:
            found.append(typed)
        return found

    def _busy_prefix(self, prefix: str) -> int:
        return sum(
            1 for group in self._jobs.busy_groups() if group.startswith(prefix)
        )

    @staticmethod
    def _restore_target_key(target: ConnectionConfig) -> str:
        return f"{target.id}\0{target.database}"

    def _delete_target(self, backup: BackupInfo):
        """Adapter that owns this row, and a short destination name for audit."""
        destination = self.backup_manager.backup_destination(backup)
        if destination is None and self._list_source in (
            "protondrive",
            "s3",
            "googledrive",
        ):
            destination = self._list_source
        if destination:
            adapter = self.backup_manager.get_adapter(destination)
            if adapter is None:
                raise RuntimeError(f"{destination} adapter unavailable")
            return adapter, destination
        return LocalBackupAdapter(base_path=self.backup_dir), "local"

    def delete_selected(self) -> None:
        """Delete the selected local or cloud backups after confirmation."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:create")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backups = self._selected_backups()
        if not backups:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return
        if len(backups) == 1:
            backup = backups[0]
            try:
                _adapter, destination = self._delete_target(backup)
            except Exception as exc:
                self._set_status(str(exc), "fail")
                return
            labels = {
                "local": t("backups.local", default="Local"),
                "protondrive": t("backups.proton_drive", default="Proton Drive"),
                "s3": t("settings.adapter_s3", default="S3-compatible"),
                "googledrive": "Google Drive",
            }
            where = labels.get(destination, destination)
            body = t(
                "backups.delete_body",
                default=(
                    "Delete {where} backup {name}? "
                    "The archive and its checksum metadata are removed. "
                    "This cannot be undone."
                ),
                where=where,
                name=backup.name,
            )
        else:
            listed = "\n".join(f"• {backup.name}" for backup in backups[:12])
            if len(backups) > 12:
                listed += f"\n• … {len(backups) - 12} more"
            body = t(
                "backups.delete_many_body",
                default=(
                    "Delete these {count} backups?\n{names}\n"
                    "The archives and their checksum metadata are removed. "
                    "This cannot be undone."
                ),
                count=len(backups),
                names=listed,
            )
        confirm = QMessageBox.warning(
            self,
            t("backups.delete_title", default="Delete backup"),
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for backup in backups:
            self._launch_delete(backup)

    def _launch_delete(self, backup: BackupInfo) -> None:
        """Delete one backup on its own worker. Does not touch other rows."""
        t = self.i18n.translate
        backup_id = backup.id
        backup_name = backup.name
        local_dir = self.backup_dir
        list_source = self._list_source

        def job() -> str:
            adapter, dest = self._delete_target(backup)
            if dest == "local":
                adapter = LocalBackupAdapter(base_path=local_dir)
            try:
                asyncio.run(adapter.delete_backup(backup_id))
            except Exception as exc:
                write_audit(
                    "backup.delete",
                    "failed",
                    backup_id=backup_id,
                    name=backup_name,
                    destination=dest,
                    error=str(exc)[:400],
                )
                raise
            write_audit(
                "backup.delete",
                "completed",
                backup_id=backup_id,
                name=backup_name,
                destination=dest,
            )
            return dest

        def on_ok(dest: str) -> None:
            self._row_outcomes.pop(backup_id, None)
            self._set_status(
                t(
                    "backups.delete_done",
                    default="Deleted {name}.",
                    name=backup_name,
                ),
                "pass",
            )
            if list_source == "local" or dest == "local":
                self.refresh_backups(queue=True)
            else:
                self.refresh_remote_backups(list_source, queue=True)

        def on_fail(message: str) -> None:
            detail = (message or "").strip().replace("{", "{{").replace("}", "}}")
            text = t(
                "backups.delete_failed",
                default="Delete failed: {error}",
                error=detail or "unknown error",
            )
            self._set_row_outcome(backup_id, "fail", "FAIL", text)
            self._set_status(text, "fail")

        self._set_row_outcome(backup_id, "restoring", "Deleting…", "Deleting…")
        self._run_backup_job(
            job,
            group=f"delete:{backup_id}",
            busy_message=t(
                "backups.delete_in_progress",
                default="Deleting backup…",
            ),
            on_ok=on_ok,
            on_fail=on_fail,
        )

    def verify_selected(self) -> None:
        """Verify SHA-256 for each selected backup (one worker per backup)."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:read")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backups = self._selected_backups()
        if not backups:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return
        for backup in backups:
            self._launch_verify(backup)

    def _launch_verify(self, backup: BackupInfo) -> None:
        t = self.i18n.translate
        manager = self.backup_manager
        backup_id = backup.id

        def job() -> Dict[str, Any]:
            # Adapter-aware: Proton rows are remote objects, not local paths.
            return manager.verify_backup(backup)

        def on_ok(result: Dict[str, Any]) -> None:
            current = self._row_outcomes.get(backup_id)
            if current and current.get("status") == "Verifying…":
                self._row_outcomes.pop(backup_id, None)
            self._verify_results[backup.id] = result
            self._verify_results[backup.path] = result
            self._populate_table()
            if self._busy_prefix("verify:"):
                self._set_status(
                    t(
                        "backups.verify_n_progress",
                        default="Verifying {count} backups…",
                        count=self._busy_prefix("verify:"),
                    ),
                    "restoring",
                )
            else:
                self._present_checksum_result(result, single=True)

        def on_fail(message: str) -> None:
            self._set_row_outcome(backup_id, "fail", "FAIL", message or "Verify failed")
            self._set_status(message or "Verify failed", "fail")

        self._set_row_outcome(backup_id, "restoring", "Verifying…", "Verifying…")
        self._run_backup_job(
            job,
            group=f"verify:{backup_id}",
            busy_message=t("backups.verify_in_progress", default="Verifying backup…"),
            on_ok=on_ok,
            on_fail=on_fail,
        )

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

        backups = list(self._backups)
        manager = self.backup_manager

        def job() -> List[Dict[str, Any]]:
            return manager.verify_backups_parallel(backups)

        def on_ok(results: List[Dict[str, Any]]) -> None:
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

        self._run_backup_job(
            job,
            group=_GROUP_VERIFY,
            busy_message=t(
                "backups.verify_all_in_progress",
                default="Verifying all backups…",
            ),
            on_ok=on_ok,
        )

    def _prompt_passphrase(self, backup_name: str) -> Optional[str]:
        """Ask for the DSMENC1 passphrase (never stored); None when cancelled."""
        t = self.i18n.translate
        text, ok = QInputDialog.getText(
            self,
            t("backups.passphrase_title", default="Encryption passphrase"),
            t(
                "backups.passphrase_prompt",
                default="Passphrase for {name}:",
                name=backup_name,
            ),
            QLineEdit.EchoMode.Password,
        )
        text = text.strip()
        return text if ok and text else None

    def dry_run_selected(self) -> None:
        """Checksum + payload dry-run for each selected backup."""
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:restore")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backups = self._selected_backups()
        if not backups:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return
        for backup in backups:
            candidates = self._passphrase_candidates(backup)
            if (backup.metadata or {}).get("encryption") and not candidates:
                prompted = self._prompt_passphrase(backup.name)
                if not prompted:
                    self._set_status(
                        t(
                            "backups.dry_run_passphrase_required",
                            default="Encrypted backup: enter the encryption passphrase to run a dry-run restore.",
                        ),
                        "missing_checksum",
                    )
                    self._set_row_outcome(
                        backup.id,
                        "missing_checksum",
                        "FAIL",
                        t(
                            "backups.dry_run_passphrase_required",
                            default="Encrypted backup: enter the encryption passphrase to run a dry-run restore.",
                        ),
                    )
                    continue
                candidates = [prompted]
            passphrase = candidates[0] if candidates else None
            rest = candidates[1:]
            self._launch_dry_run(backup, passphrase, rest)

    def _launch_dry_run(
        self,
        backup: BackupInfo,
        passphrase: Optional[str],
        rest: List[str],
    ) -> None:
        """Dry-run one backup. ``rest`` is tried if this passphrase is rejected."""
        t = self.i18n.translate
        manager = self.backup_manager
        backup_id = backup.id

        def job() -> Dict[str, Any]:
            local_info = backup
            temp_download: Optional[Path] = None
            try:
                if manager.is_remote_backup(backup):
                    adapter = manager.get_adapter(
                        manager.backup_destination(backup) or "protondrive"
                    )
                    if adapter is None:
                        return {
                            "ok": False,
                            "status": "not_configured",
                            "error": "Backup destination adapter unavailable",
                        }
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
                return manager.dry_run_restore(local_info, encryption_key=passphrase)
            finally:
                if temp_download is not None:
                    temp_download.unlink(missing_ok=True)

        def on_ok(result: Any) -> None:
            mismatch = (
                isinstance(result, dict)
                and not result.get("ok")
                and "passphrase does not match" in str(result.get("error") or "")
            )
            if mismatch and rest:
                self._launch_dry_run(backup, rest[0], rest[1:])
                return
            try:
                text, kind = self._dry_run_outcome(result)
            except Exception as exc:  # noqa: BLE001 — status must not stay on "in progress"
                text, kind = self._dry_run_failure(str(exc) or type(exc).__name__), "fail"
            if kind == "pass":
                self._remember_passphrase(backup, passphrase)
                detail = "Dry-run OK"
                code = "pass"
                label = "PASS"
            else:
                detail = ""
                if isinstance(result, dict):
                    detail = str(result.get("error") or "")
                detail = detail or text
                code = "fail"
                label = "FAIL"
            self._set_row_outcome(backup_id, code, label, detail)
            if isinstance(result, dict):
                self._verify_results[backup.id] = result
                self._verify_results[backup.path] = result
            if self._busy_prefix("dry-run:"):
                self._set_status(
                    t(
                        "backups.dry_run_n_progress",
                        default="Dry-run {count} backups…",
                        count=self._busy_prefix("dry-run:"),
                    ),
                    "restoring",
                )
            else:
                self._set_status(text, kind)

        def on_fail(message: str) -> None:
            text = self._dry_run_failure(message)
            self._set_row_outcome(backup_id, "fail", "FAIL", message or text)
            self._set_status(text, "fail")

        self._set_row_outcome(backup_id, "restoring", "Dry-run…", "Dry-run…")
        self._run_backup_job(
            job,
            group=f"dry-run:{backup_id}",
            busy_message=t(
                "backups.dry_run_in_progress",
                default="Dry-run restore in progress…",
            ),
            on_ok=on_ok,
            on_fail=on_fail,
        )

    def _restore_targets(self) -> List[ConnectionConfig]:
        targets: List[ConnectionConfig] = []
        for conn in self.connections or []:
            cfg = self._as_connection_config(conn)
            if cfg is not None:
                targets.append(cfg)
        return targets

    def restore_selected(self) -> None:
        """Full restore of each selected backup (one worker per backup)."""
        t = self.i18n.translate
        if not is_restore_enabled():
            self._set_status(
                t(
                    "backups.restore_disabled",
                    default="Full restore is turned off. Enable it under Settings → Backups & Adapters.",
                ),
                "not_configured",
            )
            return
        try:
            get_auth_manager().require("backups:restore")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return
        backups = self._selected_backups()
        if not backups:
            self._set_status(t("backups.no_backup_selected"), "missing_checksum")
            return
        targets = self._restore_targets()
        if not targets:
            self._set_status(t("backups.no_connection_selected"), "fail")
            return

        if len(backups) == 1:
            backup = backups[0]
            dialog = RestoreDialog(
                backup,
                targets,
                passphrase=self._known_passphrase(backup),
                parent=self,
            )
            if dialog.exec() != RestoreDialog.DialogCode.Accepted:
                return
            values = dialog.result_values()
            target: ConnectionConfig = values["target"]
            final = QMessageBox.warning(
                self,
                t("restore.final_title", default="Final confirmation"),
                t(
                    "restore.final_body",
                    default="Overwrite database {database} on {connection} with {backup}? This cannot be undone.",
                    database=BackupManager.restore_confirmation_phrase(target),
                    connection=target.name,
                    backup=backup.name,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if final != QMessageBox.StandardButton.Yes:
                return
            self._launch_restore(backup, values)
            return

        dialog = RestoreBatchDialog(
            backups,
            targets,
            passphrases={
                backup.id: self._known_passphrase(backup) for backup in backups
            },
            parent=self,
        )
        if dialog.exec() != RestoreBatchDialog.DialogCode.Accepted:
            return
        values = dialog.result_values()
        target = values["target"]
        listed = "\n".join(f"• {backup.name}" for backup in backups)
        final = QMessageBox.warning(
            self,
            t("restore.final_title", default="Final confirmation"),
            t(
                "restore.final_batch_body",
                default=(
                    "Overwrite database {database} on {connection} with these "
                    "{count} backups?\n{names}\nThis cannot be undone."
                ),
                database=BackupManager.restore_confirmation_phrase(target),
                connection=target.name,
                count=len(backups),
                names=listed,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if final != QMessageBox.StandardButton.Yes:
            return
        per_pass = values.get("passphrases") or {}
        for backup in backups:
            one = dict(values)
            if (backup.metadata or {}).get("encryption"):
                one["passphrase"] = per_pass.get(backup.id) or self._known_passphrase(
                    backup
                )
            else:
                one["passphrase"] = None
            self._launch_restore(backup, one)

    def _launch_restore(self, backup: BackupInfo, values: Dict[str, Any]) -> None:
        """Start one restore. A second restore of the same database waits."""
        t = self.i18n.translate
        target: ConnectionConfig = values["target"]
        group = f"restore:{backup.id}"
        if self._jobs.is_busy(group):
            self._set_row_outcome(
                backup.id,
                "restoring",
                "Restoring…",
                "Already restoring this backup",
            )
            return
        target_key = self._restore_target_key(target)
        if target_key in self._restore_busy_targets:
            waiting = self._restore_wait.setdefault(target_key, [])
            if all(item[0].id != backup.id for item in waiting):
                waiting.append((backup, values))
            self._set_row_outcome(backup.id, "restoring", "Queued…", "Queued…")
            return
        self._restore_busy_targets.add(target_key)

        manager = self.backup_manager
        local_dir = self.backup_dir
        destination = manager.backup_destination(backup)
        backup_id = backup.id

        def job() -> Dict[str, Any]:
            if destination:
                adapter = manager.get_adapter(destination)
                if adapter is None:
                    raise RuntimeError("Backup destination adapter unavailable")
            else:
                adapter = LocalBackupAdapter(base_path=local_dir)
            if values.get("scratch"):
                return asyncio.run(
                    manager.scratch_restore(
                        adapter,
                        backup,
                        target,
                        confirmation=values["confirmation"],
                        encryption_key=values.get("passphrase"),
                    )
                )
            return asyncio.run(
                manager.full_restore(
                    adapter,
                    backup,
                    target,
                    confirmation=values["confirmation"],
                    encryption_key=values.get("passphrase"),
                    safety_backup_dir=(
                        Path(local_dir) if values.get("safety_backup") else None
                    ),
                    safety_passphrase=values.get("safety_passphrase"),
                )
            )

        def _after(text: str, kind: str) -> None:
            self._finish_restore_target(target_key)
            if self._busy_prefix("restore:"):
                self._set_status(
                    t(
                        "backups.restore_n_progress",
                        default="Restoring {count} backups…",
                        count=self._busy_prefix("restore:"),
                    ),
                    "restoring",
                )
            else:
                self._set_status(text, kind)

        def on_ok(result: Any) -> None:
            try:
                text, kind = self._restore_outcome(result)
            except Exception as exc:  # noqa: BLE001 — status must not stay on "in progress"
                text, kind = (
                    self._restore_failure_text(str(exc) or type(exc).__name__),
                    "fail",
                )
            if kind == "pass":
                self._remember_passphrase(backup, values.get("passphrase"))
                if isinstance(result, dict) and result.get("safetyBackup"):
                    self._remember_passphrase(
                        None,
                        values.get("safety_passphrase"),
                        name=str(result.get("safetyBackup")),
                    )
                self._set_row_outcome(backup_id, "pass", "PASS", "Restored")
                self.refresh_backups(queue=True, keep_status=True)
            else:
                self._set_row_outcome(
                    backup_id,
                    "fail",
                    "FAIL",
                    str(result.get("error") or text) if isinstance(result, dict) else text,
                )
            _after(text, kind)

        def on_fail(message: str) -> None:
            text = self._restore_failure_text(message)
            self._set_row_outcome(backup_id, "fail", "FAIL", message or text)
            _after(text, "fail")

        self._set_row_outcome(backup_id, "restoring", "Restoring…", "Restoring…")
        started = self._run_backup_job(
            job,
            group=group,
            busy_message=t(
                "backups.restore_in_progress", default="Restoring backup…"
            ),
            on_ok=on_ok,
            on_fail=on_fail,
        )
        if not started:
            self._set_row_outcome(
                backup_id,
                "restoring",
                "Restoring…",
                "Already restoring this backup",
            )
            self._finish_restore_target(target_key)

    def _finish_restore_target(self, target_key: str) -> None:
        """Allow the next queued restore of this database to start."""
        self._restore_busy_targets.discard(target_key)
        waiting = self._restore_wait.get(target_key) or []
        if not waiting:
            self._restore_wait.pop(target_key, None)
            return
        nxt_backup, nxt_values = waiting.pop(0)
        if not waiting:
            self._restore_wait.pop(target_key, None)
        self._launch_restore(nxt_backup, nxt_values)

    def _reload_schedules_table(self) -> None:
        """Refresh the scheduled backups table from disk."""
        if not hasattr(self, "schedules_table"):
            return
        schedules = self.schedule_manager.get_schedules()
        self.schedules_table.setRowCount(0)
        for schedule in schedules:
            row = self.schedules_table.rowCount()
            self.schedules_table.insertRow(row)
            last = (
                schedule.last_run.strftime("%Y-%m-%d %H:%M:%S")
                if schedule.last_run
                else "—"
            )
            values = [
                schedule.name,
                ", ".join(schedule.connections)
                if isinstance(schedule.connections, list)
                else str(schedule.connections),
                schedule.adapter_type,
                f"{schedule.interval_minutes}"
                f"{self.i18n.translate('backups.schedule_minutes_suffix', default=' min')}",
                self.i18n.translate("common.yes")
                if schedule.enabled
                else self.i18n.translate("common.no"),
                last,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, schedule.id)
                self.schedules_table.setItem(row, col, item)

    def _selected_schedule_id(self) -> Optional[str]:
        if not hasattr(self, "schedules_table"):
            return None
        rows = self.schedules_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.schedules_table.item(rows[0].row(), 0)
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") or None

    def _add_schedule(self) -> None:
        t = self.i18n.translate
        try:
            get_auth_manager().require("backups:create")
        except PermissionDenied as exc:
            self._set_status(str(exc), "fail")
            return

        name = self.schedule_name_edit.text().strip()
        connection = self._as_connection_config(
            self.schedule_connection_combo.currentData()
        )
        if not name:
            self._set_status(
                t("backups.schedule_name_required", default="Schedule name is required"),
                "fail",
            )
            return
        if connection is None:
            self._set_status(t("backups.no_connection_selected"), "fail")
            return

        adapter_type = str(self.schedule_adapter_combo.currentData() or "local")
        encrypt = (
            True
            if adapter_type in ENCRYPTED_ADAPTERS
            else self.schedule_encrypt_checkbox.isChecked()
        )
        enc_key = self.schedule_passphrase_edit.text().strip() or None
        if encrypt and not enc_key:
            self._set_status(t("backups.encryption_key_required"), "fail")
            return

        self.schedule_manager.create_schedule(
            {
                "name": name,
                "intervalMinutes": int(self.schedule_interval_spin.value()),
                "enabled": True,
                "adapterType": adapter_type,
                "adapterConfig": {
                    "encryption": encrypt,
                    "encryptionKey": enc_key,
                    "compression": "none",
                },
                "connections": [connection.id],
            }
        )
        if not self.schedule_manager.running:
            self.schedule_manager.start()
        self.schedule_name_edit.clear()
        self._reload_schedules_table()
        self._set_status(
            t("backups.schedule_added", default="Schedule “{name}” added", name=name),
            "pass",
        )

    def _toggle_selected_schedule(self) -> None:
        schedule_id = self._selected_schedule_id()
        if not schedule_id:
            self._set_status(
                self.i18n.translate(
                    "backups.schedule_none_selected",
                    default="Select a schedule first",
                ),
                "fail",
            )
            return
        schedule = self.schedule_manager.get_schedule(schedule_id)
        if schedule is None:
            return
        payload = schedule.to_dict()
        payload["enabled"] = not schedule.enabled
        # to_dict uses camelCase keys matching create/update
        self.schedule_manager.update_schedule(
            {
                "id": payload["id"],
                "name": payload["name"],
                "intervalMinutes": payload["intervalMinutes"],
                "enabled": payload["enabled"],
                "adapterType": payload["adapterType"],
                "adapterConfig": payload.get("adapterConfig"),
                "connections": payload["connections"],
            }
        )
        if payload["enabled"] and not self.schedule_manager.running:
            self.schedule_manager.start()
        self._reload_schedules_table()

    def _remove_selected_schedule(self) -> None:
        schedule_id = self._selected_schedule_id()
        if not schedule_id:
            self._set_status(
                self.i18n.translate(
                    "backups.schedule_none_selected",
                    default="Select a schedule first",
                ),
                "fail",
            )
            return
        self.schedule_manager.delete_schedule(schedule_id)
        self._reload_schedules_table()

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

    @staticmethod
    def _status_detail(message: str, fallback: str) -> str:
        """One line safe to pass through ``str.format`` placeholders."""
        detail = (message or "").strip().replace("{", "{{").replace("}", "}}")
        return detail or fallback

    def _restore_failure_text(self, message: str) -> str:
        t = self.i18n.translate
        detail = self._status_detail(message, "unknown error")
        text = t(
            "backups.restore_failed",
            default="Restore failed: {error}",
            error=detail,
        )
        return (text or "").strip() or f"Restore failed: {detail}"

    def _restore_outcome(self, result: Any) -> tuple:
        """Success or failure text for a finished full or scratch restore.

        A missing message, a notice-only result, and a PostgreSQL skipped-ACL
        note all become a visible line. ``ok: False`` (including an empty
        error) is a failure. ``None`` is a finished restore with no extra note.
        """
        t = self.i18n.translate
        if isinstance(result, dict) and result.get("ok") is False:
            return self._restore_failure_text(str(result.get("error") or "")), "fail"
        if result is not None and not isinstance(result, dict):
            return (
                self._restore_failure_text("Restore finished without a result."),
                "fail",
            )
        notice = ""
        if isinstance(result, dict):
            notice = str(result.get("restoreNotice") or "").strip()
            if result.get("scratch"):
                text = t(
                    "backups.scratch_done",
                    default="Scratch restore finished in {name}. Production was not modified.",
                    name=result.get("scratchDatabase") or "",
                )
            else:
                safety = result.get("safetyBackup")
                text = (
                    t(
                        "backups.restore_done_safety",
                        default="Restore finished. Safety backup: {name}.",
                        name=safety,
                    )
                    if safety
                    else t("backups.restore_done", default="Restore finished.")
                )
        else:
            text = t("backups.restore_done", default="Restore finished.")
        text = (text or "").strip()
        if notice:
            text = f"{text} {notice}".strip()
        if not text:
            text = (
                t("backups.restore_done", default="Restore finished.").strip()
                or "Restore finished."
            )
        return text, "pass"

    def _dry_run_failure(self, message: str, stage: str = "dry_run") -> str:
        t = self.i18n.translate
        error = self._status_detail(
            message,
            t("backups.dry_run_failed", default="Dry-run restore failed"),
        )
        text = t(
            "backups.dry_run_fail",
            default="FAIL — dry-run restore failed at {stage}: {error}",
            stage=stage or "dry_run",
            error=error,
        )
        shown = (text or "").strip()
        return shown or f"FAIL — dry-run restore failed at {stage}: {error}"

    def _dry_run_outcome(self, result: Any) -> tuple:
        """Success or failure text for a finished dry-run restore."""
        t = self.i18n.translate
        if not isinstance(result, dict):
            return self._dry_run_failure(""), "fail"
        if result.get("ok"):
            integrity = result.get("integrity")
            detail = (
                t("backups.dry_run_pass_integrity", integrity=integrity)
                if integrity
                else t(
                    "backups.dry_run_pass",
                    default="PASS — dry-run restore succeeded (checksum OK, payload readable).",
                )
            )
            detail = (detail or "").strip() or "PASS — dry-run restore succeeded."
            return detail, "pass"
        stage = str(result.get("stage") or "dry_run")
        error = str(
            result.get("error")
            or t("backups.dry_run_failed", default="Dry-run restore failed")
        )
        return self._dry_run_failure(error, stage), str(result.get("status") or "fail")

    def _set_status(self, text: str, status: str) -> None:
        shown = (text or "").strip()
        kind = status or "fail"
        if not shown:
            shown = self._restore_failure_text("")
            kind = "fail"
        color = _STATUS_COLORS.get(kind, _STATUS_COLORS["unknown"])
        self.verify_status_label.setText(shown)
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
