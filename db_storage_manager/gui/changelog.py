"""Read-only changelog window.

The Updates tab keeps the channel and the GitHub check. The changelog is a
document, so it opens here from Help, the tray, and a button on Updates.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from ..i18n.manager import get_i18n_manager
from ..resources import apply_app_icon
from ..updates import load_changelog
from .utils import apply_glassmorphism


class ChangelogDialog(QDialog):
    """Local CHANGELOG.md in its own window. No network."""

    def __init__(
        self,
        parent=None,
        *,
        changelog_fn: Optional[Callable[[], Tuple[str, str]]] = None,
    ):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        self._changelog_fn = changelog_fn or load_changelog
        t = self.i18n.translate
        self.setWindowTitle(t("updates.changelog", default="Changelog"))
        self.setModal(True)
        self.resize(720, 520)
        apply_app_icon(self)

        layout = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(t("common.close", default="Close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        apply_glassmorphism(self)
        self.load()

    def load(self) -> None:
        try:
            text, source = self._changelog_fn()
        except Exception as exc:  # noqa: BLE001 — shown in the window
            self.view.setPlainText(
                self.i18n.translate(
                    "updates.changelog_failed",
                    error=str(exc) or type(exc).__name__,
                )
            )
            return
        self.view.setMarkdown(text)
        self.view.setToolTip(source)
