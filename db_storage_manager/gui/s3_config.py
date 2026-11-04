"""In-app S3 destination editor (SecureStore encrypted)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..backups.s3 import configuration_status, save_s3_settings
from ..i18n.manager import get_i18n_manager
from ..security.auth import PermissionDenied, get_auth_manager
from ..security.store import SecureStore


class S3ConfigDialog(QDialog):
    """Collect bucket / endpoint / keys and save them into SecureStore."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(t("s3.configure_title", default="Configure S3 backups"))
        self.setModal(True)
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        hint = QLabel(
            t(
                "s3.configure_hint",
                default=(
                    "Works with AWS S3 and S3-compatible storage (MinIO, "
                    "Cloudflare R2, Backblaze B2, Wasabi). Backups are always "
                    "encrypted before upload. Keys are stored encrypted in "
                    "SecureStore; leave them blank to keep the stored values "
                    "or to use the default AWS credential chain."
                ),
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        stored = dict(SecureStore().get_settings().get("s3_backup") or {})
        form = QFormLayout()

        self.bucket_edit = QLineEdit(str(stored.get("bucket") or ""))
        form.addRow(t("s3.bucket", default="Bucket:"), self.bucket_edit)

        self.prefix_edit = QLineEdit(str(stored.get("prefix") or ""))
        form.addRow(t("s3.prefix", default="Key prefix:"), self.prefix_edit)

        self.region_edit = QLineEdit(str(stored.get("region") or "us-east-1"))
        form.addRow(t("s3.region", default="Region:"), self.region_edit)

        self.endpoint_edit = QLineEdit(str(stored.get("endpoint") or ""))
        self.endpoint_edit.setPlaceholderText("https://s3.example.com")
        form.addRow(
            t("s3.endpoint", default="Custom endpoint (optional):"),
            self.endpoint_edit,
        )

        self.access_key_edit = QLineEdit()
        self.access_key_edit.setPlaceholderText(
            t("s3.keep_existing", default="Leave blank to keep existing")
        )
        form.addRow(t("s3.access_key", default="Access key ID:"), self.access_key_edit)

        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_edit.setPlaceholderText(
            t("s3.keep_existing", default="Leave blank to keep existing")
        )
        form.addRow(t("s3.secret_key", default="Secret access key:"), self.secret_edit)
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
                self, t("auth.denied", default="Access denied"), str(exc)
            )
            return

        bucket = self.bucket_edit.text().strip()
        if not bucket:
            QMessageBox.warning(
                self,
                t("common.error", default="Error"),
                t("s3.bucket_required", default="A bucket name is required."),
            )
            return

        key_id = self.access_key_edit.text().strip()
        secret = self.secret_edit.text()
        if bool(key_id) != bool(secret.strip()):
            stored = dict(SecureStore().get_settings().get("s3_backup") or {})
            if not (stored.get("accessKeyId") and stored.get("secretAccessKey")):
                QMessageBox.warning(
                    self,
                    t("common.error", default="Error"),
                    t(
                        "s3.keys_together",
                        default="Enter the access key ID and secret together.",
                    ),
                )
                return

        save_s3_settings(
            bucket=bucket,
            prefix=self.prefix_edit.text().strip(),
            region=self.region_edit.text().strip() or "us-east-1",
            endpoint=self.endpoint_edit.text().strip(),
            access_key_id=key_id or None,
            secret_access_key=secret if secret.strip() else None,
        )
        status = configuration_status()
        QMessageBox.information(
            self,
            t("common.success", default="Success"),
            t(
                "s3.saved",
                default="S3 settings saved for bucket {bucket}.",
                bucket=status.get("bucket") or bucket,
            ),
        )
        self.accept()


def open_s3_config(parent=None) -> bool:
    """Show the dialog; return True when the user saved."""
    return S3ConfigDialog(parent).exec() == QDialog.DialogCode.Accepted
