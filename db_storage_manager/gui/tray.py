"""Application system tray: left-click toggles the window, right-click opens the menu.

Behaviour (matches common desktop conventions and what Qt reports per platform):

* **Left click** (``Trigger``) - show / hide the main window.
* **Double click** - always show and raise the window.
* **Middle click** - jump to the Backups tab (quick backup status).
* **Right click** - context menu: Show/Hide, Dashboard / Backups / Monitoring,
  live status lines (monitoring + backups), Changelog, Check for updates, Quit.

Desktop notifications use ``QSystemTrayIcon.showMessage`` with a configurable
auto-dismiss timeout (Settings -> notification seconds, default 5, clamped
2-60). Some desktops treat the timeout as a hint only.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..i18n.manager import get_i18n_manager
from ..monitoring.alerts import AlertSeverity

DEFAULT_NOTIFICATION_SECONDS = 5
MIN_NOTIFICATION_SECONDS = 2
MAX_NOTIFICATION_SECONDS = 60


def clamp_notification_seconds(value) -> int:
    """Normalize a user setting to the supported auto-dismiss range."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NOTIFICATION_SECONDS
    return max(MIN_NOTIFICATION_SECONDS, min(MAX_NOTIFICATION_SECONDS, seconds))


class AppTray(QObject):
    """System tray icon wired to a main window through simple callbacks."""

    quit_requested = pyqtSignal()

    def __init__(
        self,
        window: QWidget,
        *,
        timeout_seconds: int = DEFAULT_NOTIFICATION_SECONDS,
        status_provider: Optional[Callable[[], "tuple[str, str]"]] = None,
        open_section: Optional[Callable[[str], None]] = None,
        open_changelog: Optional[Callable[[], None]] = None,
        open_check_updates: Optional[Callable[[], None]] = None,
        tray: Optional[QSystemTrayIcon] = None,
    ):
        super().__init__(window)
        self.window = window
        self.i18n = get_i18n_manager()
        self._status_provider = status_provider
        self._open_section = open_section
        self._open_changelog = open_changelog
        self._open_check_updates = open_check_updates
        self._timeout_seconds = clamp_notification_seconds(timeout_seconds)
        self.icon = tray or QSystemTrayIcon(self)
        icon = window.windowIcon()
        self.icon.setIcon(icon if not icon.isNull() else QIcon())
        self._build_menu()
        self.icon.activated.connect(self._on_activated)
        self.retranslate()

    # -- availability / lifecycle ----------------------------------------

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self.icon.setVisible(True)

    def hide(self) -> None:
        self.icon.setVisible(False)

    # -- menu --------------------------------------------------------------

    def _build_menu(self) -> None:
        self.menu = QMenu()
        self.toggle_action = QAction(self.menu)
        self.toggle_action.triggered.connect(self.toggle_window)
        self.menu.addAction(self.toggle_action)
        self.menu.addSeparator()

        self.dashboard_action = QAction(self.menu)
        self.dashboard_action.triggered.connect(lambda: self._goto("dashboard"))
        self.backups_action = QAction(self.menu)
        self.backups_action.triggered.connect(lambda: self._goto("backups"))
        self.monitoring_action = QAction(self.menu)
        self.monitoring_action.triggered.connect(lambda: self._goto("monitoring"))
        for action in (
            self.dashboard_action,
            self.backups_action,
            self.monitoring_action,
        ):
            self.menu.addAction(action)
        self.menu.addSeparator()

        self.monitoring_status_action = QAction(self.menu)
        self.monitoring_status_action.setEnabled(False)
        self.backups_status_action = QAction(self.menu)
        self.backups_status_action.setEnabled(False)
        self.menu.addAction(self.monitoring_status_action)
        self.menu.addAction(self.backups_status_action)
        self.menu.addSeparator()

        self.changelog_action = QAction(self.menu)
        self.changelog_action.triggered.connect(self._show_changelog)
        self.menu.addAction(self.changelog_action)
        self.check_updates_action = QAction(self.menu)
        self.check_updates_action.triggered.connect(self._show_check_updates)
        self.menu.addAction(self.check_updates_action)
        self.quit_action = QAction(self.menu)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.quit_action)

        self.menu.aboutToShow.connect(self.refresh_status)
        self.icon.setContextMenu(self.menu)

    def retranslate(self) -> None:
        t = self.i18n.translate
        self.icon.setToolTip(t("app.title", default="DB Storage Manager"))
        self.dashboard_action.setText(t("tabs.dashboard"))
        self.backups_action.setText(t("tabs.backups"))
        self.monitoring_action.setText(t("tabs.monitoring"))
        self.changelog_action.setText(t("tray.changelog", default="Changelog"))
        self.check_updates_action.setText(
            t("tray.check_updates", default="Check for updates")
        )
        self.quit_action.setText(t("tray.quit"))
        self.refresh_status()

    def refresh_status(self) -> None:
        """Update Show/Hide label and the monitoring / backups status lines."""
        t = self.i18n.translate
        self.toggle_action.setText(
            t("tray.hide") if self.window.isVisible() else t("tray.show")
        )
        monitoring, backups = (
            self._status_provider() if self._status_provider else ("", "")
        )
        self.monitoring_status_action.setText(monitoring or t("tray.monitoring_idle"))
        self.backups_status_action.setText(backups or t("tray.backups_idle"))
        tooltip = t("app.title", default="DB Storage Manager")
        if monitoring or backups:
            tooltip = "\n".join(x for x in (tooltip, monitoring, backups) if x)
        self.icon.setToolTip(tooltip)

    # -- click handling -----------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self._goto("backups")
        # ``Context`` (right click) is handled by the platform via setContextMenu.

    def show_window(self) -> None:
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.refresh_status()

    def toggle_window(self) -> None:
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
            self.refresh_status()
        else:
            self.show_window()

    def _goto(self, section: str) -> None:
        self.show_window()
        if self._open_section is not None:
            self._open_section(section)

    def _show_changelog(self) -> None:
        self.show_window()
        if self._open_changelog is not None:
            self._open_changelog()

    def _show_check_updates(self) -> None:
        self.show_window()
        if self._open_check_updates is not None:
            self._open_check_updates()

    # -- notifications --------------------------------------------------------

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    def set_timeout_seconds(self, seconds) -> None:
        self._timeout_seconds = clamp_notification_seconds(seconds)

    def notify(self, title: str, message: str, severity: str = "warning") -> None:
        """Show a desktop notification that auto-dismisses after the timeout."""
        icon = QSystemTrayIcon.MessageIcon.Warning
        if severity == AlertSeverity.CRITICAL.value:
            icon = QSystemTrayIcon.MessageIcon.Critical
        elif severity == AlertSeverity.INFO.value:
            icon = QSystemTrayIcon.MessageIcon.Information
        self.icon.showMessage(title, message, icon, self._timeout_seconds * 1000)
