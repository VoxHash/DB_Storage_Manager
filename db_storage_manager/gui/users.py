"""Users / RBAC admin panel for shared workstation deployments."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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
from ..security.auth import (
    PermissionDenied,
    UserRole,
    get_auth_manager,
)
from ..security.bootstrap import bootstrap_admin
from ..security.store import SecureStore
from .utils import apply_glassmorphism


class _UserDialog(QDialog):
    """Create or edit a local user (role / password)."""

    def __init__(
        self,
        *,
        title: str,
        username: str = "",
        email: str = "",
        role: UserRole = UserRole.USER,
        username_editable: bool = True,
        require_password: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)
        self.require_password = require_password
        layout = QFormLayout(self)
        self.username_edit = QLineEdit(username)
        self.username_edit.setEnabled(username_editable)
        layout.addRow("Username", self.username_edit)
        self.email_edit = QLineEdit(email)
        layout.addRow("Email", self.email_edit)
        self.role_combo = QComboBox()
        for r in UserRole:
            self.role_combo.addItem(r.value, r)
        idx = self.role_combo.findData(role)
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)
        layout.addRow("Role", self.role_combo)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Password", self.password_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self):
        return {
            "username": self.username_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "role": self.role_combo.currentData(),
            "password": self.password_edit.text(),
        }


class UsersAdminWidget(QWidget):
    """Bootstrap + manage local users (admin)."""

    users_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        self.secure_store = SecureStore()
        self._build()
        self.refresh()

    def _build(self) -> None:
        t = self.i18n.translate
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.group = QGroupBox(
            t("auth.users_group", default="Users & RBAC")
        )
        g_layout = QVBoxLayout(self.group)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        g_layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Username", "Email", "Role", "Enabled", "Last login"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        g_layout.addWidget(self.table)

        actions = QHBoxLayout()
        self.bootstrap_btn = QPushButton(
            t("auth.bootstrap", default="Bootstrap first admin…")
        )
        self.bootstrap_btn.clicked.connect(self._bootstrap)
        actions.addWidget(self.bootstrap_btn)

        self.add_btn = QPushButton(t("auth.add_user", default="Add user…"))
        self.add_btn.clicked.connect(self._add_user)
        actions.addWidget(self.add_btn)

        self.role_btn = QPushButton(
            t("auth.change_role", default="Change role…")
        )
        self.role_btn.clicked.connect(self._change_role)
        actions.addWidget(self.role_btn)

        self.password_btn = QPushButton(
            t("auth.reset_password", default="Reset password…")
        )
        self.password_btn.clicked.connect(self._reset_password)
        actions.addWidget(self.password_btn)

        self.toggle_btn = QPushButton(
            t("auth.toggle_enabled", default="Enable / Disable")
        )
        self.toggle_btn.clicked.connect(self._toggle_enabled)
        actions.addWidget(self.toggle_btn)

        self.delete_btn = QPushButton(
            t("auth.delete_user", default="Delete user")
        )
        self.delete_btn.clicked.connect(self._delete_user)
        actions.addWidget(self.delete_btn)
        actions.addStretch()
        g_layout.addLayout(actions)

        layout.addWidget(self.group)
        apply_glassmorphism(self)

    def refresh(self) -> None:
        auth = get_auth_manager()
        auth.reload()
        users = auth.list_users()
        active = auth.is_rbac_active()
        current = auth.current_user
        if not active:
            self.status_label.setText(
                "RBAC inactive (single-user open mode). "
                "Bootstrap a local admin to require sign-in on this "
                "workstation. CLI: db-storage-manager-bootstrap"
            )
        else:
            who = current.username if current else "(not signed in)"
            self.status_label.setText(
                f"RBAC active — {len(users)} user(s). "
                f"Signed in as: {who}"
            )
        self.bootstrap_btn.setEnabled(not active)
        can_manage = auth.has_permission("users:manage")
        self.add_btn.setEnabled(active and can_manage)
        self.role_btn.setEnabled(active and can_manage)
        self.password_btn.setEnabled(active and can_manage)
        self.toggle_btn.setEnabled(active and can_manage)
        self.delete_btn.setEnabled(active and can_manage)

        self.table.setRowCount(len(users))
        for row, user in enumerate(users):
            values = [
                user.username,
                user.email,
                user.role.value,
                "Yes" if user.enabled else "No",
                user.last_login or "—",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def _selected_username(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _bootstrap(self) -> None:
        dlg = _UserDialog(
            title="Bootstrap first admin",
            role=UserRole.ADMIN,
            require_password=True,
            parent=self,
        )
        # Force admin role in bootstrap dialog
        dlg.role_combo.setCurrentIndex(dlg.role_combo.findData(UserRole.ADMIN))
        dlg.role_combo.setEnabled(False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        try:
            bootstrap_admin(
                vals["username"],
                vals["password"],
                email=vals["email"],
                store=self.secure_store,
            )
            auth = get_auth_manager()
            auth.reload()
            auth.authenticate(vals["username"], vals["password"])
        except (ValueError, RuntimeError) as exc:
            QMessageBox.critical(self, "Bootstrap failed", str(exc))
            return
        QMessageBox.information(
            self,
            "RBAC enabled",
            f"Admin '{vals['username']}' created. "
            "Sign-in is now required on this workstation.",
        )
        self.refresh()
        self.users_changed.emit()

    def _add_user(self) -> None:
        dlg = _UserDialog(title="Add user", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        try:
            get_auth_manager().create_user(
                vals["username"],
                vals["password"],
                email=vals["email"],
                role=vals["role"] or UserRole.USER,
            )
        except (ValueError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Add user", str(exc))
            return
        self.refresh()
        self.users_changed.emit()

    def _change_role(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        auth = get_auth_manager()
        user = auth.get_user(username)
        if not user:
            return
        dlg = _UserDialog(
            title=f"Change role — {username}",
            username=username,
            email=user.email,
            role=user.role,
            username_editable=False,
            require_password=False,
            parent=self,
        )
        dlg.password_edit.setEnabled(False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            auth.set_user_role(username, dlg.values()["role"])
        except (ValueError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Change role", str(exc))
            return
        self.refresh()
        self.users_changed.emit()

    def _reset_password(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        dlg = _UserDialog(
            title=f"Reset password — {username}",
            username=username,
            username_editable=False,
            require_password=True,
            parent=self,
        )
        dlg.email_edit.setEnabled(False)
        dlg.role_combo.setEnabled(False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            get_auth_manager().set_password(
                username, dlg.values()["password"]
            )
        except (ValueError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Reset password", str(exc))
            return
        QMessageBox.information(self, "Users", "Password updated.")
        self.refresh()

    def _toggle_enabled(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        auth = get_auth_manager()
        user = auth.get_user(username)
        if not user:
            return
        try:
            auth.set_user_enabled(username, not user.enabled)
        except (ValueError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Enable / Disable", str(exc))
            return
        self.refresh()
        self.users_changed.emit()

    def _delete_user(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        reply = QMessageBox.question(
            self,
            "Delete user",
            f"Delete user '{username}'?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            get_auth_manager().delete_user(username)
        except (ValueError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Delete user", str(exc))
            return
        self.refresh()
        self.users_changed.emit()
