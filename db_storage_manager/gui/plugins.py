"""
Local plugin marketplace UI — list, enable/disable, install from path/URL.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n.manager import get_i18n_manager
from ..config import SPONSORS_URL
from ..plugins.licensing import PluginLicenseError, PluginLicenseRequired
from ..plugins.pricing import format_pricing
from ..plugins.marketplace import LocalPluginMarketplace
from ..plugins.manifest import ManifestError
from ..security.auth import PermissionDenied, get_auth_manager
from ..themes.manager import get_theme_manager
from .icons import set_icon_only, set_icon_with_text
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
        self.setObjectName("glassmorphism")
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
            self.activate_license_btn,
            self.deactivate_license_btn,
        ):
            btn.setEnabled(can_manage)
        # Opening a public checkout page is not a privileged action.
        self.get_license_btn.setEnabled(auth.has_permission("plugins:read"))
        self.sponsor_btn.setEnabled(auth.has_permission("plugins:read"))
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
                        "Built-in plugins are free. Third-party plugins install from a "
                        "folder with plugin.json or an http(s) zip/tar.gz URL; premium "
                        "plugins also need a LicenseChain license key. Enable/disable "
                        "is saved locally. No remote catalog is shipped yet."
                    ),
                ),
            )
        )

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                t("plugins.col_id", default="ID"),
                t("plugins.col_name", default="Name"),
                t("plugins.col_version", default="Version"),
                t("plugins.col_type", default="Type"),
                t("plugins.col_source", default="Source"),
                t("plugins.col_enabled", default="Enabled"),
                t("plugins.col_license", default="License"),
                t("plugins.col_author", default="Author"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_dense_table(self.table)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton()
        set_icon_only(
            self.refresh_btn, "refresh", t("plugins.refresh", default="Refresh")
        )
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

        license_actions = QHBoxLayout()
        self.activate_license_btn = QPushButton(
            t("plugins.license_activate", default="Activate License…")
        )
        set_icon_with_text(self.activate_license_btn, "key")
        self.activate_license_btn.clicked.connect(self._activate_license)
        license_actions.addWidget(self.activate_license_btn)

        self.get_license_btn = QPushButton(
            t("plugins.license_get", default="Get License")
        )
        set_icon_with_text(self.get_license_btn, "external")
        self.get_license_btn.clicked.connect(self._open_purchase_page)
        license_actions.addWidget(self.get_license_btn)

        self.sponsor_btn = QPushButton(
            t("plugins.support_dsm", default="Support DSM")
        )
        set_icon_with_text(self.sponsor_btn, "external")
        self.sponsor_btn.setToolTip(
            t(
                "plugins.support_dsm_tip",
                default=(
                    "The core app and built-in tools stay free. Optional "
                    "GitHub Sponsors donations keep them maintained."
                ),
            )
        )
        self.sponsor_btn.clicked.connect(self._open_sponsors_page)
        license_actions.addWidget(self.sponsor_btn)

        self.deactivate_license_btn = QPushButton(
            t("plugins.license_deactivate", default="Deactivate License")
        )
        self.deactivate_license_btn.clicked.connect(self._deactivate_license)
        license_actions.addWidget(self.deactivate_license_btn)
        license_actions.addStretch()

        actions.addStretch()
        layout.addLayout(actions)
        layout.addLayout(license_actions)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        apply_glassmorphism(self)

    def refresh(self) -> None:
        t = self.i18n.translate
        self._rows = self.marketplace.list_installed()
        enabled_map = self.marketplace.get_enabled_map()
        theme = get_theme_manager()
        self.table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            plugin_id = row["id"]
            enabled = bool(enabled_map.get(plugin_id, True))
            # Cache-only: refreshing the table must never block on the network.
            license_status = self.marketplace.license_status(plugin_id)
            # A premium plugin without an active license is effectively off.
            enabled = enabled and license_status.allowed
            license_text = self._license_label(license_status)
            values = [
                plugin_id,
                row.get("name", ""),
                row.get("version", ""),
                row.get("plugin_type", ""),
                row.get("source", ""),
                t("common.yes", default="Yes")
                if enabled
                else t("common.no", default="No"),
                license_text,
                row.get("author", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 5:
                    # Theme tokens, not fixed dark-on-dark Qt colours.
                    item.setForeground(
                        QColor(
                            theme.get_color("success" if enabled else "error")
                        )
                    )
                elif col == 6 and license_status.state != "not_required":
                    item.setForeground(
                        QColor(
                            theme.get_color(
                                "success" if license_status.allowed else "warning"
                            )
                        )
                    )
                    if license_status.masked_key:
                        item.setToolTip(
                            f"{license_status.message} ({license_status.masked_key})"
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
        try:
            self.marketplace.set_enabled(row["id"], enabled)
        except PluginLicenseError as exc:
            self._license_blocked(row, exc)
            return
        self.refresh()

    # ---------------------------------------------------------- licensing

    def _license_label(self, status) -> str:
        t = self.i18n.translate
        labels = {
            "not_required": t("plugins.license_free", default="Free"),
            "licensed": t("plugins.license_ok", default="Licensed"),
            "grace": t("plugins.license_grace", default="Licensed (offline)"),
            "missing": t("plugins.license_missing", default="Not activated"),
            "invalid": t("plugins.license_invalid", default="Invalid"),
            "expired": t("plugins.license_expired", default="Expired"),
            "mismatch": t("plugins.license_mismatch", default="Wrong product"),
            "unverified": t(
                "plugins.license_unverified", default="Needs online check"
            ),
        }
        return labels.get(status.state, status.state)

    def _license_blocked(self, row: dict, exc: PluginLicenseError) -> None:
        """Explain why a premium plugin cannot be enabled / run and offer next steps."""
        t = self.i18n.translate
        QMessageBox.warning(
            self,
            t("plugins.license_required", default="License required"),
            t(
                "plugins.license_blocked_msg",
                default=(
                    "'{id}' is a premium plugin: {reason}.\n"
                    "Use Activate License… (or Get License to buy one)."
                ),
                id=row["id"],
                reason=str(exc),
            ),
        )

    def _prompt_license(self, requirement, plugin_label: str):
        """Ask for a LicenseChain key. Returns the key or ``None`` when cancelled."""
        t = self.i18n.translate
        key, ok = QInputDialog.getText(
            self,
            t("plugins.license_activate", default="Activate License…"),
            t(
                "plugins.license_key_prompt",
                default=(
                    "'{name}' needs a LicenseChain license ({price}).\n"
                    "Updates are included. Buy one at {url}\nthen paste the key:"
                ),
                name=plugin_label,
                price=(
                    format_pricing(requirement.pricing)
                    if requirement and requirement.pricing
                    else "-"
                ),
                url=requirement.purchase_url if requirement else "",
            ),
            QLineEdit.EchoMode.Password,
        )
        key = key.strip()
        return key if ok and key else None

    def _prompt_email(self):
        t = self.i18n.translate
        email, ok = QInputDialog.getText(
            self,
            t("plugins.license_email_title", default="Purchase email"),
            t(
                "plugins.license_email_prompt",
                default="Email used for the purchase of this license:",
            ),
        )
        email = email.strip()
        return email if ok and email else None

    def _activate_with_prompts(self, plugin_id: str, requirement, label: str):
        """Run key (+ email) prompts and verify. Returns ``True`` when activated."""
        t = self.i18n.translate
        key = self._prompt_license(requirement, label)
        if key is None:
            return False
        email = None
        while True:
            try:
                self.marketplace.activate_license(plugin_id, key, email)
                return True
            except PluginLicenseError as exc:
                if exc.code == "email_required" and email is None:
                    email = self._prompt_email()
                    if email is None:
                        return False
                    continue
                QMessageBox.critical(
                    self,
                    t("plugins.license_failed", default="License not accepted"),
                    str(exc),
                )
                return False

    def _activate_license(self) -> None:
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
        requirement = self.marketplace.license_requirement(row["id"])
        if requirement is None:
            QMessageBox.information(
                self,
                t("plugins.title", default="Plugins"),
                t(
                    "plugins.license_not_needed",
                    default="'{id}' is a free plugin and needs no license.",
                    id=row["id"],
                ),
            )
            return
        if self._activate_with_prompts(
            row["id"], requirement, row.get("name") or row["id"]
        ):
            self.refresh()

    def _open_purchase_page(self) -> None:
        t = self.i18n.translate
        row = self._selected_row()
        requirement = (
            self.marketplace.license_requirement(row["id"]) if row else None
        )
        if requirement is None:
            QMessageBox.information(
                self,
                t("plugins.title", default="Plugins"),
                t(
                    "plugins.license_pick_premium",
                    default="Select a premium plugin to open its LicenseChain checkout.",
                ),
            )
            return
        QDesktopServices.openUrl(QUrl(requirement.purchase_url))

    def _open_sponsors_page(self) -> None:
        QDesktopServices.openUrl(QUrl(SPONSORS_URL))

    def _deactivate_license(self) -> None:
        try:
            get_auth_manager().require("plugins:manage")
        except PermissionDenied as exc:
            self._deny(exc)
            return
        t = self.i18n.translate
        row = self._selected_row()
        if row is None or self.marketplace.license_requirement(row["id"]) is None:
            QMessageBox.information(
                self,
                t("plugins.title", default="Plugins"),
                t(
                    "plugins.license_pick_premium",
                    default="Select a premium plugin to open its LicenseChain checkout.",
                ),
            )
            return
        confirm = QMessageBox.question(
            self,
            t("plugins.license_deactivate", default="Deactivate License"),
            t(
                "plugins.license_deactivate_confirm",
                default="Remove the stored license for '{id}' from this computer?",
                id=row["id"],
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.marketplace.deactivate_license(row["id"])
        self.refresh()

    def _install_with_license(self, install_fn) -> dict | None:
        """Run an install; if the plugin is premium, collect a key and retry."""
        t = self.i18n.translate
        try:
            return install_fn()
        except PluginLicenseRequired as exc:
            requirement = exc.requirement
            key = self._prompt_license(
                requirement,
                getattr(exc, "plugin_name", None) or requirement.product_id,
            )
            if key is None:
                return None
            email = None
            while True:
                try:
                    return install_fn(license_key=key, license_email=email)
                except PluginLicenseError as inner:
                    if inner.code == "email_required" and email is None:
                        email = self._prompt_email()
                        if email is None:
                            return None
                        continue
                    QMessageBox.critical(
                        self,
                        t("plugins.license_failed", default="License not accepted"),
                        str(inner),
                    )
                    return None

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
            installed = self._install_with_license(
                lambda **kw: self.marketplace.install_from_path(
                    Path(path), replace=True, **kw
                )
            )
        except (ManifestError, OSError, RuntimeError) as exc:
            QMessageBox.critical(
                self,
                t("plugins.install_failed", default="Install failed"),
                str(exc),
            )
            return
        if installed is None:
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
            installed = self._install_with_license(
                lambda **kw: self.marketplace.install_from_url(
                    url.strip(), replace=True, **kw
                )
            )
        except (ManifestError, OSError, RuntimeError) as exc:
            QMessageBox.critical(
                self,
                t("plugins.install_failed", default="Install failed"),
                str(exc),
            )
            return
        if installed is None:
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
