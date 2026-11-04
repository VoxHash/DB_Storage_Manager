"""Updates tab: channel and a manual GitHub release check.

The changelog opens in its own window. Nothing is downloaded or installed.
An automatic check is a separate opt-in (default off, at most once a day).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_VERSION
from ..i18n.manager import get_i18n_manager
from ..security.store import SecureStore
from ..updates import (
    CHANNEL_EXPERIMENTAL,
    CHANNEL_STABLE,
    RELEASES_PAGE,
    ReleaseInfo,
    auto_check_due,
    check_for_update,
    is_trusted_release_url,
    load_changelog,
)
from .jobs import JobRunner


class UpdatesPanel(QWidget):
    """Update channel and GitHub check. The changelog is a separate window."""

    update_available = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        check_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        changelog_fn: Optional[Callable[[], Any]] = None,
        open_url_fn: Optional[Callable[[str], Any]] = None,
    ):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        self._check_fn = check_fn or (lambda channel: check_for_update(channel))
        self._changelog_fn = changelog_fn or load_changelog
        self._open_url = open_url_fn or (
            lambda url: QDesktopServices.openUrl(QUrl(url))
        )
        self._jobs = JobRunner(self)
        self._jobs.state_changed.connect(self._sync_check_button)
        self._release: Optional[ReleaseInfo] = None
        t = self.i18n.translate

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.current_label = QLabel(t("updates.current", version=APP_VERSION))
        layout.addWidget(self.current_label)

        row = QHBoxLayout()
        self.channel_label = QLabel(t("updates.channel"))
        row.addWidget(self.channel_label)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem(t("updates.channel_stable"), CHANNEL_STABLE)
        self.channel_combo.addItem(
            t("updates.channel_experimental"), CHANNEL_EXPERIMENTAL
        )
        saved = self._saved_channel()
        idx = self.channel_combo.findData(saved)
        self.channel_combo.setCurrentIndex(max(idx, 0))
        row.addWidget(self.channel_combo)
        self.check_button = QPushButton(t("updates.check"))
        self.check_button.setObjectName("PrimaryButton")
        self.check_button.clicked.connect(lambda: self.check_updates(notify=False))
        row.addWidget(self.check_button)
        row.addStretch()
        layout.addLayout(row)

        self.hint_label = QLabel(t("updates.channel_hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("SettingsHint")
        layout.addWidget(self.hint_label)

        self.auto_check = QCheckBox(t("updates.auto_check"))
        self.auto_check.setChecked(self._saved_auto_check())
        layout.addWidget(self.auto_check)
        self.auto_hint = QLabel(t("updates.auto_check_hint"))
        self.auto_hint.setWordWrap(True)
        self.auto_hint.setObjectName("SettingsHint")
        layout.addWidget(self.auto_hint)

        self.result_label = QLabel(t("updates.idle"))
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        actions = QHBoxLayout()
        self.download_button = QPushButton(t("updates.open_download"))
        self.download_button.clicked.connect(self.open_download_page)
        self.download_button.setEnabled(False)
        actions.addWidget(self.download_button)
        self.copy_pip_button = QPushButton(t("updates.copy_pip"))
        self.copy_pip_button.clicked.connect(self.copy_pip_command)
        self.copy_pip_button.setEnabled(False)
        actions.addWidget(self.copy_pip_button)
        self.releases_button = QPushButton(t("updates.open_releases"))
        self.releases_button.clicked.connect(lambda: self._open_url(RELEASES_PAGE))
        actions.addWidget(self.releases_button)
        self.changelog_button = QPushButton(t("updates.open_changelog", default="Changelog…"))
        self.changelog_button.clicked.connect(self.open_changelog)
        actions.addWidget(self.changelog_button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch(1)

    def retranslate(self) -> None:
        t = self.i18n.translate
        self.current_label.setText(t("updates.current", version=APP_VERSION))
        self.channel_label.setText(t("updates.channel"))
        self.channel_combo.setItemText(0, t("updates.channel_stable"))
        self.channel_combo.setItemText(1, t("updates.channel_experimental"))
        self.check_button.setText(t("updates.check"))
        self.hint_label.setText(t("updates.channel_hint"))
        self.auto_check.setText(t("updates.auto_check"))
        self.auto_hint.setText(t("updates.auto_check_hint"))
        self.download_button.setText(t("updates.open_download"))
        self.copy_pip_button.setText(t("updates.copy_pip"))
        self.releases_button.setText(t("updates.open_releases"))
        self.changelog_button.setText(
            t("updates.open_changelog", default="Changelog…")
        )

    def selected_channel(self) -> str:
        return str(self.channel_combo.currentData() or CHANNEL_STABLE)

    def auto_check_enabled(self) -> bool:
        return self.auto_check.isChecked()

    def set_editable(self, editable: bool) -> None:
        """Channel and the opt-in are preferences. The check button stays usable."""
        self.channel_combo.setEnabled(editable)
        self.auto_check.setEnabled(editable)

    @staticmethod
    def _saved_channel() -> str:
        try:
            value = SecureStore().get_settings().get("update_channel")
        except Exception:
            value = None
        return value if value in (CHANNEL_STABLE, CHANNEL_EXPERIMENTAL) else CHANNEL_STABLE

    @staticmethod
    def _saved_auto_check() -> bool:
        try:
            return bool(SecureStore().get_settings().get("update_auto_check"))
        except Exception:
            return False

    def open_changelog(self) -> None:
        """Open the local changelog in its own window."""
        from .changelog import ChangelogDialog

        dialog = ChangelogDialog(self, changelog_fn=self._changelog_fn)
        dialog.exec()

    def check_updates(self, *, notify: bool = False, channel: Optional[str] = None) -> None:
        channel = channel or self.selected_channel()
        t = self.i18n.translate
        self._release = None
        self.download_button.setEnabled(False)
        self.copy_pip_button.setEnabled(False)

        def on_ok(result: Dict[str, Any]) -> None:
            update = result.get("update")
            latest = result.get("latest")
            if update is not None:
                self._release = update
                self.download_button.setEnabled(True)
                self.copy_pip_button.setEnabled(True)
                kind = (
                    t("updates.experimental_tag")
                    if update.prerelease
                    else t("updates.stable_tag")
                )
                self.result_label.setText(
                    t(
                        "updates.available",
                        version=update.label,
                        current=APP_VERSION,
                        kind=kind,
                    )
                )
                if notify:
                    self.update_available.emit(self.result_label.text())
            elif latest is not None:
                self.result_label.setText(
                    t("updates.up_to_date", version=APP_VERSION, latest=latest.label)
                )
            else:
                self.result_label.setText(t("updates.no_releases"))

        def on_fail(message: str) -> None:
            self.result_label.setText(t("updates.check_failed", error=message))

        self._jobs.submit(
            "check",
            lambda: self._check_fn(channel),
            on_ok,
            on_fail,
            on_start=lambda: (
                self.check_button.setEnabled(False),
                self.result_label.setText(t("updates.checking")),
            ),
        )

    def maybe_auto_check(self) -> None:
        """One public GitHub request when the user opted in and the interval elapsed."""
        try:
            store = SecureStore()
            settings = store.get_settings()
        except Exception:
            return
        if not settings.get("update_auto_check"):
            return
        now = datetime.now(timezone.utc)
        if not auto_check_due(settings.get("update_auto_check_at"), now):
            return
        settings["update_auto_check_at"] = now.replace(microsecond=0).isoformat()
        try:
            store.set_settings(settings)
        except Exception:
            return
        channel = settings.get("update_channel")
        if channel not in (CHANNEL_STABLE, CHANNEL_EXPERIMENTAL):
            channel = CHANNEL_STABLE
        self.check_updates(notify=True, channel=channel)

    def _sync_check_button(self) -> None:
        self.check_button.setEnabled(not self._jobs.is_busy("check"))

    def open_download_page(self) -> None:
        if self._release is not None and is_trusted_release_url(self._release.html_url):
            self._open_url(self._release.html_url)

    def copy_pip_command(self) -> None:
        if self._release is not None:
            QGuiApplication.clipboard().setText(self._release.pip_command)

    def wait_idle(self, timeout_ms: int = 5000) -> None:
        """Pump events until background lookups finish (tests)."""
        import time

        from PyQt6.QtCore import QCoreApplication

        deadline = time.monotonic() + timeout_ms / 1000.0
        while self._jobs.any_busy() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        QCoreApplication.processEvents()
