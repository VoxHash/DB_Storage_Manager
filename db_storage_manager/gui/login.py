"""Login dialog for multi-user / RBAC sessions."""

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

from ..i18n.manager import get_i18n_manager
from ..security.auth import get_auth_manager
from .utils import apply_glassmorphism


class LoginDialog(QDialog):
    """Prompt for username / password (+ optional MFA) before MainWindow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(t("auth.login_title", default="Sign in"))
        self.setModal(True)
        self.setMinimumWidth(360)
        self._build()
        apply_glassmorphism(self)

    def _build(self) -> None:
        t = self.i18n.translate
        layout = QVBoxLayout(self)
        hint = QLabel(
            t(
                "auth.login_hint",
                default=(
                    "This workstation has multi-user RBAC enabled. "
                    "Sign in with a local account."
                ),
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("admin")
        form.addRow(
            t("auth.username", default="Username"), self.username_edit
        )
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(
            t("auth.password", default="Password"), self.password_edit
        )
        self.mfa_edit = QLineEdit()
        self.mfa_edit.setPlaceholderText(
            t("auth.mfa_optional", default="MFA code (if enabled)")
        )
        form.addRow(t("auth.mfa", default="MFA"), self.mfa_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _try_login(self) -> None:
        t = self.i18n.translate
        auth = get_auth_manager()
        user = auth.authenticate(
            self.username_edit.text().strip(),
            self.password_edit.text(),
            mfa_token=self.mfa_edit.text().strip() or None,
        )
        if user is None:
            QMessageBox.warning(
                self,
                t("auth.login_failed", default="Sign in failed"),
                t(
                    "auth.login_failed_msg",
                    default="Invalid credentials or MFA code.",
                ),
            )
            return
        self.accept()
