"""
Main entry point for DB Storage Manager
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from .gui.main_window import MainWindow
from .config import APP_NAME, APP_VERSION
from .resources import apply_app_icon, load_app_icon


def main():
    """Main application entry point"""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("VoxHash")

    # Window / taskbar / dock icon from packaged resources
    app.setWindowIcon(load_app_icon())

    # Set application style
    app.setStyle("Fusion")

    # Initialize i18n and theme managers
    from .i18n.manager import get_i18n_manager
    from .themes.manager import get_theme_manager
    from .gui.utils import apply_theme_to_app

    get_i18n_manager()  # Initialize i18n
    get_theme_manager()  # Initialize theme

    # Apply theme to application
    apply_theme_to_app(app)

    # Multi-user RBAC: require sign-in when local users exist
    from .security.auth import get_auth_manager
    from .gui.login import LoginDialog
    from PyQt6.QtWidgets import QDialog

    auth = get_auth_manager()
    if auth.is_rbac_active():
        login = LoginDialog()
        apply_app_icon(login)
        if login.exec() != QDialog.DialogCode.Accepted:
            return 1

    # Create and show main window
    window = MainWindow()
    apply_app_icon(window)
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
