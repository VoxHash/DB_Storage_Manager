"""In-app Proton Drive credential editor (SecureStore encrypted)."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..backups.protondrive import (
    configuration_status,
    save_proton_drive_credentials,
)
from ..i18n.manager import get_i18n_manager
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore


class ProtonDriveConfigDialog(QDialog):
    """Collect Proton username/password/OTP and save into SecureStore."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(
            t("backups.proton_configure_title", default="Configure Proton Drive")
        )
        self.setModal(True)
        self.resize(480, 280)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                t(
                    "backups.proton_configure_hint",
                    default=(
                        "Credentials are stored encrypted in SecureStore "
                        "(never committed). Leave password blank to keep "
                        "the existing value."
                    ),
                )
            )
        )

        form = QFormLayout()
        stored = dict(SecureStore().get_settings().get("proton_drive") or {})

        self.username_edit = QLineEdit()
        self.username_edit.setText(str(stored.get("username") or ""))
        self.username_edit.setPlaceholderText("name@proton.me")
        form.addRow(
            t("backups.proton_username", default="Proton username:"),
            self.username_edit,
        )

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(
            t(
                "backups.proton_password_placeholder",
                default="Leave blank to keep existing",
            )
        )
        form.addRow(
            t("backups.proton_password", default="Proton password:"),
            self.password_edit,
        )

        self.otp_edit = QLineEdit()
        self.otp_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if stored.get("otp_secret_key"):
            self.otp_edit.setPlaceholderText(
                t("backups.proton_otp_set", default="OTP secret already set — leave blank to keep")
            )
        else:
            self.otp_edit.setPlaceholderText(
                t("backups.proton_otp_placeholder", default="Optional TOTP secret")
            )
        form.addRow(
            t("backups.proton_otp", default="OTP secret (optional):"),
            self.otp_edit,
        )

        self.prefer_enc_check = QCheckBox(
            t(
                "backups.proton_prefer_encryption",
                default="Prefer DSMENC1 encryption before upload",
            )
        )
        self.prefer_enc_check.setChecked(bool(stored.get("prefer_encryption", True)))
        form.addRow("", self.prefer_enc_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        t = self.i18n.translate
        try:
            get_auth_manager().require("settings:write")
        except PermissionDenied as exc:
            QMessageBox.warning(
                self,
                t("auth.denied", default="Access denied"),
                str(exc),
            )
            return

        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        otp = self.otp_edit.text().strip()
        if not username:
            QMessageBox.warning(
                self,
                t("common.error", default="Error"),
                t(
                    "backups.proton_username_required",
                    default="Proton username is required.",
                ),
            )
            return

        stored = dict(SecureStore().get_settings().get("proton_drive") or {})
        if not password.strip() and not stored.get("password"):
            QMessageBox.warning(
                self,
                t("common.error", default="Error"),
                t(
                    "backups.proton_password_required",
                    default="Proton password is required (or configure an rclone remote).",
                ),
            )
            return

        save_proton_drive_credentials(
            username=username,
            password=password if password.strip() else None,
            otp_secret_key=otp if otp else None,
            prefer_encryption=self.prefer_enc_check.isChecked(),
        )
        status = configuration_status()
        if status.get("configured"):
            QMessageBox.information(
                self,
                t("common.success", default="Success"),
                t(
                    "backups.proton_saved_ready",
                    default="Proton Drive credentials saved. Status: ready.",
                ),
            )
        else:
            QMessageBox.warning(
                self,
                t("common.success", default="Success"),
                t(
                    "backups.proton_saved_incomplete",
                    default="Credentials saved, but Proton Drive is not ready yet: {error}",
                    error=status.get("error") or status.get("message") or "",
                ),
            )
        self.accept()


def open_proton_drive_config(parent=None) -> bool:
    """Show the config dialog; return True if the user saved."""
    dialog = ProtonDriveConfigDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
