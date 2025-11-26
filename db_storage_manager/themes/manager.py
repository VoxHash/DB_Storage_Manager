"""
Theme manager
"""

import json
from pathlib import Path
from typing import Dict, Optional
from .themes import THEMES, DEFAULT_THEME
from ..config import USER_DATA_DIR

THEME_FILE = USER_DATA_DIR / "theme.json"


class ThemeManager:
    """Manages application themes"""

    def __init__(self):
        self.current_theme = DEFAULT_THEME
        self.load_theme_preference()

    def load_theme_preference(self) -> None:
        """Load saved theme preference"""
        if THEME_FILE.exists():
            try:
                with open(THEME_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    theme = data.get("theme", DEFAULT_THEME)
                    if theme in THEMES:
                        self.current_theme = theme
            except Exception:
                pass

    def save_theme_preference(self) -> None:
        """Save theme preference"""
        try:
            THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(THEME_FILE, "w", encoding="utf-8") as f:
                json.dump({"theme": self.current_theme}, f, indent=2)
        except Exception:
            pass

    def set_theme(self, theme: str) -> None:
        """Set current theme"""
        if theme in THEMES:
            self.current_theme = theme
            self.save_theme_preference()

    def get_theme(self) -> Dict:
        """Get current theme configuration"""
        return THEMES.get(self.current_theme, THEMES[DEFAULT_THEME])

    def get_color(self, color_name: str) -> str:
        """Get a color from current theme"""
        theme = self.get_theme()
        return theme["colors"].get(color_name, "#000000")

    def get_glassmorphism_style(self) -> str:
        """Get glassmorphism CSS style"""
        theme = self.get_theme()
        glass = theme["glassmorphism"]
        return f"""
            background-color: {glass['background']};
            border: 1px solid {glass['border']};
            border-radius: 12px;
        """


# Global instance
_theme_manager: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    """Get global theme manager instance"""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
