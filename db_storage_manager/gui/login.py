"""Login dialog for multi-user / RBAC sessions."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..i18n.manager import get_i18n_manager
from ..security.auth import get_auth_manager
from ..resources import apply_app_icon
from .utils import apply_theme_to_app


class LoginDialog(QDialog):
    """Prompt for username / password (+ optional MFA) before MainWindow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(t("auth.login_title", default="Sign in"))
        apply_app_icon(self)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setMinimumHeight(280)
        apply_theme_to_app(self)
        self._build()

    def _build(self) -> None:
        t = self.i18n.translate
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)

        card = QFrame()
        card.setObjectName("LoginCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel(t("auth.login_title", default="Sign in"))
        title.setObjectName("LoginTitle")
        layout.addWidget(title)

        hint = QLabel(
            t(
                "auth.login_hint",
                default=(
                    "This workstation has multi-user RBAC enabled. "
                    "Sign in with a local account."
                ),
            )
        )
        hint.setObjectName("LoginHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
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
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setObjectName("PrimaryButton")
            ok_btn.setText(t("auth.sign_in", default="Sign in"))
        buttons.accepted.connect(self._try_login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        outer.addWidget(card)

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
