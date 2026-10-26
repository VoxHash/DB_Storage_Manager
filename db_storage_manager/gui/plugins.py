"""
Local plugin marketplace UI — list, enable/disable, install from path/URL.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n.manager import get_i18n_manager
from ..plugins.marketplace import LocalPluginMarketplace
from ..plugins.manifest import ManifestError
from ..security.auth import PermissionDenied, get_auth_manager
from .utils import (
    apply_glassmorphism,
    apply_page_layout,
    configure_dense_table,
    make_page_header,
)


class PluginsWidget(QWidget):
    """Desktop surface for the local plugin registry / marketplace."""

    def __init__(self, marketplace: LocalPluginMarketplace | None = None):
        super().__init__()
        self.i18n = get_i18n_manager()
        self.marketplace = marketplace or LocalPluginMarketplace()
        self.marketplace.sync_builtins()
        self.marketplace.load_into_manager(only_enabled=False)
        self._rows: list[dict] = []
        self.init_ui()
        self.refresh()
        self.apply_rbac()

    def apply_rbac(self) -> None:
        auth = get_auth_manager()
        can_manage = auth.has_permission("plugins:manage")
        for btn in (
            self.enable_btn,
            self.disable_btn,
            self.install_path_btn,
            self.install_url_btn,
            self.uninstall_btn,
        ):
            btn.setEnabled(can_manage)
        self.refresh_btn.setEnabled(auth.has_permission("plugins:read"))

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        apply_page_layout(layout)

        t = self.i18n.translate
        layout.addWidget(
            make_page_header(
                t("tabs.plugins"),
                t(
                    "plugins.hint",
                    default=(
                        "Built-in and user-installed plugins. Enable/disable is saved "
                        "locally. Install from a folder with plugin.json, or from an "
                        "http(s) zip/tar.gz URL. No remote catalog is shipped yet."
                    ),
                ),
            )
        )

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                t("plugins.col_id", default="ID"),
                t("plugins.col_name", default="Name"),
                t("plugins.col_version", default="Version"),
                t("plugins.col_type", default="Type"),
                t("plugins.col_source", default="Source"),
                t("plugins.col_enabled", default="Enabled"),
                t("plugins.col_author", default="Author"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_dense_table(self.table)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton(t("plugins.refresh", default="Refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)

        self.enable_btn = QPushButton(t("plugins.enable", default="Enable"))
        self.enable_btn.clicked.connect(lambda: self._set_selected_enabled(True))
        actions.addWidget(self.enable_btn)

        self.disable_btn = QPushButton(t("plugins.disable", default="Disable"))
        self.disable_btn.clicked.connect(lambda: self._set_selected_enabled(False))
        actions.addWidget(self.disable_btn)

        self.install_path_btn = QPushButton(
            t("plugins.install_path", default="Install from Path…")
        )
        self.install_path_btn.clicked.connect(self._install_from_path)
        actions.addWidget(self.install_path_btn)

        self.install_url_btn = QPushButton(
            t("plugins.install_url", default="Install from URL…")
        )
        self.install_url_btn.clicked.connect(self._install_from_url)
        actions.addWidget(self.install_url_btn)

        self.uninstall_btn = QPushButton(
            t("plugins.uninstall", default="Uninstall")
        )
        self.uninstall_btn.clicked.connect(self._uninstall_selected)
        actions.addWidget(self.uninstall_btn)

        actions.addStretch()
        layout.addLayout(actions)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        apply_glassmorphism(self)

    def refresh(self) -> None:
        t = self.i18n.translate
        self._rows = self.marketplace.list_installed()
        enabled_map = self.marketplace.get_enabled_map()
        self.table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            plugin_id = row["id"]
            enabled = bool(enabled_map.get(plugin_id, True))
            values = [
                plugin_id,
                row.get("name", ""),
                row.get("version", ""),
                row.get("plugin_type", ""),
                row.get("source", ""),
                t("common.yes", default="Yes")
                if enabled
                else t("common.no", default="No"),
                row.get("author", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 5:
                    item.setForeground(
                        Qt.GlobalColor.darkGreen
                        if enabled
                        else Qt.GlobalColor.darkRed
                    )
                self.table.setItem(row_idx, col, item)
        self.status_label.setText(
            t(
                "plugins.status_count",
                default="{count} plugin(s) in local registry",
                count=len(self._rows),
            )
        )

    def _selected_row(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._rows):
            return None
        return self._rows[idx]

    def _deny(self, exc: PermissionDenied) -> None:
        QMessageBox.warning(
            self,
            self.i18n.translate("auth.denied", default="Access denied"),
            str(exc),
        )

    def _set_selected_enabled(self, enabled: bool) -> None:
        try:
            get_auth_manager().require("plugins:manage")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        row = self._selected_row()
        if row is None:
            QMessageBox.information(
                self,
                self.i18n.translate("plugins.title", default="Plugins"),
                self.i18n.translate(
                    "plugins.select_first", default="Select a plugin first."
                ),
            )
            return
        self.marketplace.set_enabled(row["id"], enabled)
        self.refresh()

    def _install_from_path(self) -> None:
        try:
            get_auth_manager().require("plugins:manage")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        t = self.i18n.translate
        path = QFileDialog.getExistingDirectory(
            self,
            t("plugins.pick_dir", default="Select plugin directory (with plugin.json)"),
        )
        if not path:
            return
        try:
            installed = self.marketplace.install_from_path(Path(path), replace=True)
        except (ManifestError, OSError, RuntimeError) as exc:
            QMessageBox.critical(
                self,
                t("plugins.install_failed", default="Install failed"),
                str(exc),
            )
            return
        QMessageBox.information(
            self,
            t("plugins.install_ok", default="Plugin installed"),
            t(
                "plugins.install_ok_msg",
                default="Installed {name} ({id}) v{version}",
                name=installed.get("name"),
                id=installed.get("id"),
                version=installed.get("version"),
            ),
        )
        self.refresh()

    def _install_from_url(self) -> None:
        try:
            get_auth_manager().require("plugins:manage")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        t = self.i18n.translate
        url, ok = QInputDialog.getText(
            self,
            t("plugins.install_url", default="Install from URL…"),
            t(
                "plugins.url_prompt",
                default="HTTPS URL to a .zip or .tar.gz plugin archive:",
            ),
        )
        if not ok or not url.strip():
            return
        try:
            installed = self.marketplace.install_from_url(url.strip(), replace=True)
        except (ManifestError, OSError, RuntimeError) as exc:
            QMessageBox.critical(
                self,
                t("plugins.install_failed", default="Install failed"),
                str(exc),
            )
            return
        QMessageBox.information(
            self,
            t("plugins.install_ok", default="Plugin installed"),
            t(
                "plugins.install_ok_msg",
                default="Installed {name} ({id}) v{version}",
                name=installed.get("name"),
                id=installed.get("id"),
                version=installed.get("version"),
            ),
        )
        self.refresh()

    def _uninstall_selected(self) -> None:
        try:
            get_auth_manager().require("plugins:manage")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        t = self.i18n.translate
        row = self._selected_row()
        if row is None:
            QMessageBox.information(
                self,
                t("plugins.title", default="Plugins"),
                t("plugins.select_first", default="Select a plugin first."),
            )
            return
        if row.get("source") == "builtin":
            QMessageBox.warning(
                self,
                t("plugins.uninstall", default="Uninstall"),
                t(
                    "plugins.cannot_uninstall_builtin",
                    default="Built-in plugins cannot be uninstalled. Disable them instead.",
                ),
            )
            return
        confirm = QMessageBox.question(
            self,
            t("plugins.uninstall", default="Uninstall"),
            t(
                "plugins.uninstall_confirm",
                default="Uninstall plugin '{id}'?",
                id=row["id"],
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.marketplace.uninstall(row["id"])
        except ManifestError as exc:
            QMessageBox.critical(self, t("plugins.uninstall", default="Uninstall"), str(exc))
            return
        self.refresh()
