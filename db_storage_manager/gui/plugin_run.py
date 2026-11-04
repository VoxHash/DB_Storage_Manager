"""Run dialog for the Plugins page.

Opens saved connections and calls the plugin ``execute`` method. The result
box shows ``not_available`` when the licence, engine or role cannot answer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..backups.manager import BackupManager
from ..db.base import ConnectionConfig
from ..i18n.manager import get_i18n_manager
from ..plugins.invoke import (
    RunPlan,
    execute_plan,
    format_plugin_result,
    plan_run,
    run_spec,
)
from .jobs import JobRunner
from .utils import apply_glassmorphism

_SLOT_LABELS = {
    "source_db": ("plugins.run_source", "Source"),
    "db1": ("plugins.run_source", "Source"),
    "target_db": ("plugins.run_target", "Target"),
    "db2": ("plugins.run_target", "Target"),
    "connection": ("plugins.run_connection", "Connection"),
    "other": ("plugins.run_other", "Other connection"),
    "pooled": ("plugins.run_pooled", "Pooled connection"),
}


class PluginRunDialog(QDialog):
    """Collect real arguments and run one installed plugin."""

    def __init__(
        self,
        plugin_id: str,
        profiles: List[Mapping[str, Any]],
        marketplace: Any,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.plugin_id = plugin_id
        self._profiles = [dict(profile) for profile in profiles]
        self._by_id = {
            str(profile.get("id")): profile
            for profile in self._profiles
            if profile.get("id")
        }
        self._marketplace = marketplace
        self._spec = run_spec(plugin_id)
        self._jobs = JobRunner(self)
        self.i18n = get_i18n_manager()
        t = self.i18n.translate
        self.setWindowTitle(
            t("plugins.run_title", default="Run {id}", id=plugin_id)
        )
        self.setMinimumWidth(560)
        self.source_combo: Optional[QComboBox] = None
        self.target_combo: Optional[QComboBox] = None
        self.table_edit: Optional[QLineEdit] = None
        self.tables_edit: Optional[QLineEdit] = None
        self.replace_box: Optional[QCheckBox] = None
        self.confirm_edit: Optional[QLineEdit] = None
        self.confirm_hint: Optional[QLabel] = None
        self.dest_edit: Optional[QLineEdit] = None
        self.passphrase_edit: Optional[QLineEdit] = None
        self.format_combo: Optional[QComboBox] = None
        self.redact_edit: Optional[QLineEdit] = None
        self.retention_edit: Optional[QLineEdit] = None
        self.message_edit: Optional[QLineEdit] = None
        self._build()
        apply_glassmorphism(self)

    def _build(self) -> None:
        t = self.i18n.translate
        layout = QVBoxLayout(self)
        form = QFormLayout()
        spec = self._spec
        if spec.discover_cloud:
            note = QLabel(
                t(
                    "plugins.run_discover",
                    default=(
                        "multi-cloud-discovery runs from Connections → "
                        "Discover Cloud after it is installed and licensed."
                    ),
                )
            )
            note.setWordWrap(True)
            form.addRow(note)
        slots = spec.slots
        if len(slots) >= 1:
            self.source_combo = self._connection_combo(
                optional=not slots[0].required
            )
            form.addRow(self._slot_label(slots[0].kwarg), self.source_combo)
        if len(slots) >= 2:
            self.target_combo = self._connection_combo(
                optional=not slots[1].required
            )
            self.target_combo.currentIndexChanged.connect(self._refresh_phrase)
            if slots[1].required and self.target_combo.count() > 1:
                self.target_combo.setCurrentIndex(1)
            form.addRow(self._slot_label(slots[1].kwarg), self.target_combo)
        if spec.table:
            self.table_edit = QLineEdit()
            form.addRow(
                t("plugins.run_table", default="Table"), self.table_edit
            )
        if spec.tables:
            self.tables_edit = QLineEdit()
            form.addRow(
                t("plugins.run_tables", default="Tables"),
                self.tables_edit,
            )
            form.addRow(
                QLabel(
                    t(
                        "plugins.run_tables_hint",
                        default="Comma-separated. Leave empty to copy every user table.",
                    )
                )
            )
        if spec.replace:
            self.replace_box = QCheckBox(
                t(
                    "plugins.run_replace",
                    default="Replace rows in tables that already exist",
                )
            )
            self.replace_box.toggled.connect(self._refresh_phrase)
            form.addRow(self.replace_box)
            self.confirm_edit = QLineEdit()
            form.addRow(
                t("plugins.run_confirm", default="Confirmation"),
                self.confirm_edit,
            )
            self.confirm_hint = QLabel("")
            self.confirm_hint.setWordWrap(True)
            form.addRow(self.confirm_hint)
            self._refresh_phrase()
        if spec.dest:
            dest_row = QWidget()
            dest_layout = QHBoxLayout(dest_row)
            dest_layout.setContentsMargins(0, 0, 0, 0)
            self.dest_edit = QLineEdit()
            browse = QPushButton(t("plugins.run_browse", default="Browse…"))
            browse.clicked.connect(self._browse_dest)
            dest_layout.addWidget(self.dest_edit, 1)
            dest_layout.addWidget(browse)
            form.addRow(
                t("plugins.run_dest", default="Destination"),
                dest_row,
            )
        if spec.passphrase:
            self.passphrase_edit = QLineEdit()
            self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow(
                t("plugins.run_passphrase", default="Passphrase"),
                self.passphrase_edit,
            )
        if spec.export_format:
            self.format_combo = QComboBox()
            self.format_combo.addItems(["csv", "sql", "parquet"])
            form.addRow(
                t("plugins.run_format", default="Format"),
                self.format_combo,
            )
        if spec.redact:
            self.redact_edit = QLineEdit()
            form.addRow(
                t("plugins.run_redact", default="Redact columns"),
                self.redact_edit,
            )
        if spec.retention_days:
            self.retention_edit = QLineEdit()
            form.addRow(
                t("plugins.run_retention", default="Expected retention days"),
                self.retention_edit,
            )
        if spec.message:
            self.message_edit = QLineEdit()
            form.addRow(
                t("plugins.run_message", default="Message"),
                self.message_edit,
            )
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.run_btn = QPushButton(t("plugins.run", default="Run…"))
        self.run_btn.clicked.connect(self._on_run)
        actions.addWidget(self.run_btn)
        close_btn = QPushButton(t("common.close", default="Close"))
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setMinimumHeight(180)
        layout.addWidget(self.result_box, 1)

    def _slot_label(self, kwarg: str) -> str:
        key, default = _SLOT_LABELS.get(
            kwarg, ("plugins.run_connection", "Connection")
        )
        return self.i18n.translate(key, default=default)

    def _connection_combo(self, *, optional: bool) -> QComboBox:
        combo = QComboBox()
        if optional:
            combo.addItem(
                self.i18n.translate("plugins.run_none", default="(none)"),
                "",
            )
        for profile in self._profiles:
            connection_id = str(profile.get("id") or "")
            if not connection_id:
                continue
            combo.addItem(self._profile_label(profile), connection_id)
        return combo

    def _profile_label(self, profile: Mapping[str, Any]) -> str:
        name = str(profile.get("name") or profile.get("id") or "")
        engine = str(profile.get("type") or "")
        database = str(profile.get("database") or "")
        if "/" in database or "\\" in database:
            database = database.replace("\\", "/").rsplit("/", 1)[-1]
        if database:
            return f"{name} ({engine}) — {database}"
        return f"{name} ({engine})"

    def _selected_id(self, combo: Optional[QComboBox]) -> str:
        if combo is None:
            return ""
        data = combo.currentData()
        return str(data or "")

    def form_values(self) -> Dict[str, Any]:
        """Current dialog fields. The passphrase stays in this dict only."""
        values: Dict[str, Any] = {
            "source_id": self._selected_id(self.source_combo),
            "target_id": self._selected_id(self.target_combo),
        }
        if self.table_edit is not None:
            values["table"] = self.table_edit.text()
        if self.tables_edit is not None:
            values["tables"] = self.tables_edit.text()
        if self.replace_box is not None:
            values["replace"] = self.replace_box.isChecked()
        if self.confirm_edit is not None:
            values["confirm"] = self.confirm_edit.text()
        if self.dest_edit is not None:
            values["dest"] = self.dest_edit.text()
        if self.passphrase_edit is not None:
            values["passphrase"] = self.passphrase_edit.text()
        if self.format_combo is not None:
            values["export_format"] = self.format_combo.currentText()
        if self.redact_edit is not None:
            values["redact"] = self.redact_edit.text()
        if self.retention_edit is not None:
            values["retention_days"] = self.retention_edit.text()
        if self.message_edit is not None:
            values["message"] = self.message_edit.text()
        return values

    def _refresh_phrase(self) -> None:
        if self.confirm_hint is None:
            return
        t = self.i18n.translate
        profile = self._by_id.get(self._selected_id(self.target_combo))
        if not profile:
            self.confirm_hint.setText(
                t(
                    "plugins.run_confirm_need_target",
                    default="Select a target to see the name you must type.",
                )
            )
            return
        config = ConnectionConfig(
            id=str(profile.get("id") or "run"),
            name=str(profile.get("name") or "database"),
            type=str(profile.get("type") or "sqlite"),
            database=(
                profile.get("database") if profile.get("database") else None
            ),
        )
        phrase = BackupManager.restore_confirmation_phrase(config)
        self.confirm_hint.setText(
            t(
                "plugins.run_confirm_hint",
                default=(
                    "Existing tables are kept. To replace their rows, type {phrase}."
                ),
                phrase=phrase,
            )
        )

    def _browse_dest(self) -> None:
        if self.dest_edit is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            self.i18n.translate(
                "plugins.run_dest_title",
                default="Encrypted export destination",
            ),
        )
        if path:
            self.dest_edit.setText(path)

    def _on_run(self) -> None:
        if self._jobs.is_busy("plugin-run"):
            return
        plan = plan_run(self.plugin_id, self.form_values())
        profiles = self._profiles
        marketplace = self._marketplace

        def job() -> Dict[str, Any]:
            return execute_plan(marketplace, plan, profiles)

        self.run_btn.setEnabled(False)
        started = self._jobs.submit(
            "plugin-run",
            job,
            self._show_result,
            self._show_failure,
        )
        if not started:
            self.run_btn.setEnabled(True)

    def _show_result(self, result: Any) -> None:
        self.result_box.setPlainText(format_plugin_result(result))
        self.run_btn.setEnabled(True)

    def _show_failure(self, message: str) -> None:
        self._show_result(
            {"ok": False, "status": "not_available", "reason": message}
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._jobs.is_busy("plugin-run"):
            event.ignore()
            return
        super().closeEvent(event)

    def run_plan(self) -> RunPlan:
        """Plan for the current fields, without opening a connection."""
        return plan_run(self.plugin_id, self.form_values())
