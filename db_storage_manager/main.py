"""
Main entry point for DB Storage Manager
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from .gui.main_window import MainWindow
from .config import APP_NAME, APP_VERSION


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

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
