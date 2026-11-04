"""About window: centered identity, version, and the update actions."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..config import APP_VERSION
from ..i18n.manager import get_i18n_manager
from ..resources import apply_app_icon, load_app_icon
from ..security.store import SecureStore
from ..updates import CHANNEL_EXPERIMENTAL, CHANNEL_STABLE
from .utils import apply_glassmorphism

# Date of the published stable tag. The in-app version stays on that tag.
RELEASED_ON = "2026-11-03"


def version_info_text(
    *,
    version: str = APP_VERSION,
    channel: str = CHANNEL_STABLE,
    released: str = RELEASED_ON,
) -> str:
    channel_label = "Experimental" if channel == CHANNEL_EXPERIMENTAL else "Stable"
    return "\n".join(
        [
            "DB Storage Manager",
            f"Version {version}",
            f"Channel: {channel_label}",
            f"Released: {released}",
            "© 2026 VOXHASH LABS",
        ]
    )


def saved_update_channel() -> str:
    try:
        value = SecureStore().get_settings().get("update_channel")
    except Exception:
        value = None
    if value in (CHANNEL_STABLE, CHANNEL_EXPERIMENTAL):
        return str(value)
    return CHANNEL_STABLE


class AboutDialog(QDialog):
    """Centered About window with Check for Updates and Copy version info."""

    def __init__(
        self,
        parent=None,
        *,
        on_check_updates: Optional[Callable[[], None]] = None,
        version: str = APP_VERSION,
        channel: Optional[str] = None,
        released: str = RELEASED_ON,
    ):
        super().__init__(parent)
        self.i18n = get_i18n_manager()
        self._on_check_updates = on_check_updates
        self._version = version
        self._channel = channel or saved_update_channel()
        self._released = released
        t = self.i18n.translate
        self.setWindowTitle(t("about.title", default="About DB Storage Manager"))
        self.setModal(True)
        apply_app_icon(self)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = load_app_icon()
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(72, 72))
        layout.addWidget(icon_label)

        name = QLabel(t("app.title", default="DB Storage Manager"))
        name.setObjectName("NavBrand")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)

        self.version_label = QLabel(
            t("about.version_label", default="Version {version}", version=version)
        )
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.version_label)

        channel_label = (
            t("updates.channel_experimental", default="Experimental (pre-releases)")
            if self._channel == CHANNEL_EXPERIMENTAL
            else t("updates.channel_stable", default="Stable")
        )
        self.channel_label = QLabel(
            t(
                "about.channel_line",
                default="Channel: {channel}",
                channel=channel_label,
            )
        )
        self.channel_label.setObjectName("SettingsHint")
        self.channel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.channel_label)

        self.released_label = QLabel(
            t("about.released_line", default="Released: {date}", date=released)
        )
        self.released_label.setObjectName("SettingsHint")
        self.released_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.released_label)

        description = QLabel(t("about.description"))
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        copyright_label = QLabel(
            t("about.copyright", default="© 2026 VOXHASH LABS")
        )
        copyright_label.setObjectName("SettingsHint")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_label)

        layout.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.check_button = QPushButton(
            t("about.check_updates", default="Check for Updates...")
        )
        self.check_button.clicked.connect(self._check)
        buttons.addWidget(self.check_button)
        self.copy_button = QPushButton(
            t("about.copy_version", default="Copy version info")
        )
        self.copy_button.setObjectName("PrimaryButton")
        self.copy_button.clicked.connect(self._copy)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setObjectName("SettingsHint")
        layout.addWidget(self.status_label)
        apply_glassmorphism(self)

    def version_text(self) -> str:
        return version_info_text(
            version=self._version, channel=self._channel, released=self._released
        )

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.version_text())
        self.status_label.setText(
            self.i18n.translate("about.copied", default="Version info copied.")
        )

    def _check(self) -> None:
        self.accept()
        if self._on_check_updates is not None:
            self._on_check_updates()
