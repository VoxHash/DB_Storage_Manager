"""Changelog + manual update check dialog (GitHub Releases, no auto-install)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..config import APP_VERSION
from ..i18n.manager import get_i18n_manager
from ..security.auth import get_auth_manager
from ..security.store import SecureStore
from ..updates import (
    CHANNEL_EXPERIMENTAL,
    CHANNEL_STABLE,
    RELEASES_PAGE,
    ReleaseInfo,
    check_for_update,
    is_trusted_release_url,
    load_changelog,
)
from .jobs import JobRunner


class UpdatesDialog(QDialog):
    """Show CHANGELOG.md and check GitHub Releases on demand."""

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

        self.setWindowTitle(t("updates.title", default="Changelog & Updates"))
        self.setMinimumSize(640, 520)
        layout = QVBoxLayout(self)

        self.current_label = QLabel(
            t("updates.current", version=APP_VERSION)
        )
        layout.addWidget(self.current_label)

        row = QHBoxLayout()
        row.addWidget(QLabel(t("updates.channel")))
        self.channel_combo = QComboBox()
        self.channel_combo.addItem(t("updates.channel_stable"), CHANNEL_STABLE)
        self.channel_combo.addItem(
            t("updates.channel_experimental"), CHANNEL_EXPERIMENTAL
        )
        saved = self._saved_channel()
        idx = self.channel_combo.findData(saved)
        self.channel_combo.setCurrentIndex(max(idx, 0))
        self.channel_combo.currentIndexChanged.connect(self._persist_channel)
        row.addWidget(self.channel_combo)
        self.check_button = QPushButton(t("updates.check"))
        self.check_button.setObjectName("PrimaryButton")
        self.check_button.clicked.connect(self.check_updates)
        row.addWidget(self.check_button)
        row.addStretch()
        layout.addLayout(row)

        self.hint_label = QLabel(t("updates.channel_hint"))
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

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
        self.releases_button.clicked.connect(
            lambda: self._open_url(RELEASES_PAGE)
        )
        actions.addWidget(self.releases_button)
        actions.addStretch()
        layout.addLayout(actions)

        layout.addWidget(QLabel(t("updates.changelog")))
        self.changelog_view = QTextBrowser()
        self.changelog_view.setOpenExternalLinks(False)
        self.changelog_view.setPlainText(t("updates.changelog_loading"))
        layout.addWidget(self.changelog_view, 1)

        close = QPushButton(t("common.close", default="Close"))
        close.clicked.connect(self.accept)
        layout.addWidget(close)

        self.load_changelog()

    # -- channel preference --------------------------------------------

    def selected_channel(self) -> str:
        return str(self.channel_combo.currentData() or CHANNEL_STABLE)

    @staticmethod
    def _saved_channel() -> str:
        try:
            value = SecureStore().get_settings().get("update_channel")
        except Exception:
            value = None
        return value if value in (CHANNEL_STABLE, CHANNEL_EXPERIMENTAL) else CHANNEL_STABLE

    def _persist_channel(self) -> None:
        """Remember the channel when the signed-in role may write settings."""
        if not get_auth_manager().has_permission("settings:write"):
            return
        try:
            store = SecureStore()
            settings = store.get_settings()
            settings["update_channel"] = self.selected_channel()
            store.set_settings(settings)
        except Exception:
            pass

    # -- changelog ------------------------------------------------------

    def load_changelog(self) -> None:
        def on_ok(result: Any) -> None:
            text, source = result
            self.changelog_view.setMarkdown(text)
            self.changelog_view.setToolTip(source)

        def on_fail(message: str) -> None:
            self.changelog_view.setPlainText(
                self.i18n.translate("updates.changelog_failed", error=message)
            )

        self._jobs.submit("changelog", self._changelog_fn, on_ok, on_fail)

    # -- update check ---------------------------------------------------

    def check_updates(self) -> None:
        channel = self.selected_channel()
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

    def _sync_check_button(self) -> None:
        self.check_button.setEnabled(not self._jobs.is_busy("check"))

    def open_download_page(self) -> None:
        if self._release is not None and is_trusted_release_url(
            self._release.html_url
        ):
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
