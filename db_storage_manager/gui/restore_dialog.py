"""Confirmation dialog for the experimental full Restore Backup flow."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..backups.base import BackupInfo
from ..backups.manager import BackupManager
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager


class RestoreDialog(QDialog):
    """Collect target, passphrases and a typed confirmation before a restore."""

    def __init__(
        self,
        backup: BackupInfo,
        targets: List[ConnectionConfig],
        *,
        passphrase: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        self._backup = backup
        self._targets = targets
        t = self.i18n.translate
        self.setWindowTitle(t("restore.title", default="Restore backup (experimental)"))
        self.setModal(True)
        self.resize(540, 420)

        layout = QVBoxLayout(self)
        self.warning_label = QLabel(
            t(
                "restore.warning",
                default=(
                    "Restoring {name} overwrites the data in the target "
                    "database. This cannot be undone unless you keep the "
                    "safety backup below."
                ),
                name=backup.name,
            )
        )
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        form = QFormLayout()
        self.target_combo = QComboBox()
        wanted = (backup.metadata or {}).get("connectionId")
        selected = 0
        for index, conn in enumerate(targets):
            self.target_combo.addItem(f"{conn.name} ({conn.type})", conn)
            if wanted and conn.id == wanted:
                selected = index
        self.target_combo.setCurrentIndex(selected)
        self.target_combo.currentIndexChanged.connect(self._update_confirm)
        form.addRow(t("restore.target", default="Restore into:"), self.target_combo)

        self.encrypted = bool((backup.metadata or {}).get("encryption"))
        self.passphrase_edit = QLineEdit(passphrase)
        self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_edit.setEnabled(self.encrypted)
        self.passphrase_edit.textChanged.connect(self._update_confirm)
        if self.encrypted:
            form.addRow(
                t("restore.passphrase", default="Backup passphrase:"),
                self.passphrase_edit,
            )

        self.safety_check = QCheckBox(
            t(
                "restore.safety_backup",
                default="Take an encrypted safety backup of the target first",
            )
        )
        self.safety_check.setChecked(True)
        self.safety_check.toggled.connect(self._update_confirm)
        form.addRow("", self.safety_check)

        self.safety_passphrase_edit = QLineEdit()
        self.safety_passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.safety_passphrase_edit.textChanged.connect(self._update_confirm)
        form.addRow(
            t("restore.safety_passphrase", default="Safety backup passphrase:"),
            self.safety_passphrase_edit,
        )
        self.safety_check.toggled.connect(self.safety_passphrase_edit.setEnabled)

        self.phrase_label = QLabel()
        self.phrase_label.setWordWrap(True)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.textChanged.connect(self._update_confirm)
        form.addRow(self.phrase_label, self.confirm_edit)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(t("restore.confirm_button", default="Restore"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._update_confirm()

    def target(self) -> Optional[ConnectionConfig]:
        return self.target_combo.currentData()

    def required_phrase(self) -> str:
        target = self.target()
        return BackupManager.restore_confirmation_phrase(target) if target else ""

    def _update_confirm(self, *_args) -> None:
        t = self.i18n.translate
        phrase = self.required_phrase()
        self.phrase_label.setText(
            t(
                "restore.type_to_confirm",
                default="Type {phrase} to confirm:",
                phrase=phrase,
            )
        )
        ok = bool(phrase) and self.confirm_edit.text().strip() == phrase
        if self.safety_check.isChecked():
            ok = ok and bool(self.safety_passphrase_edit.text().strip())
        if self.encrypted:
            ok = ok and bool(self.passphrase_edit.text().strip())
        self.ok_button.setEnabled(ok)

    def result_values(self) -> Dict[str, Any]:
        safety = self.safety_check.isChecked()
        return {
            "target": self.target(),
            "confirmation": self.confirm_edit.text().strip(),
            "passphrase": self.passphrase_edit.text().strip() or None,
            "safety_backup": safety,
            "safety_passphrase": (
                self.safety_passphrase_edit.text().strip() if safety else None
            ),
        }
