"""
Internationalization manager
"""

import json
from pathlib import Path
from typing import Dict, Optional
from .languages import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, RTL_LANGUAGES
from ..config import USER_DATA_DIR

TRANSLATIONS_DIR = Path(__file__).parent / "translations"
LANGUAGE_FILE = USER_DATA_DIR / "language.json"


class I18nManager:
    """Manages internationalization and translations"""

    def __init__(self):
        self.current_language = DEFAULT_LANGUAGE
        self.translations: Dict[str, Dict[str, str]] = {}
        self.load_language_preference()
        self.load_translations(self.current_language)

    def load_language_preference(self) -> None:
        """Load saved language preference"""
        if LANGUAGE_FILE.exists():
            try:
                with open(LANGUAGE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    lang = data.get("language", DEFAULT_LANGUAGE)
                    if lang in SUPPORTED_LANGUAGES:
                        self.current_language = lang
            except Exception:
                pass

    def save_language_preference(self) -> None:
        """Save language preference"""
        try:
            LANGUAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LANGUAGE_FILE, "w", encoding="utf-8") as f:
                json.dump({"language": self.current_language}, f, indent=2)
        except Exception:
            pass

    def load_translations(self, language: str) -> None:
        """Load translations for a language"""
        if language not in SUPPORTED_LANGUAGES:
            language = DEFAULT_LANGUAGE

        translation_file = TRANSLATIONS_DIR / f"{language}.json"
        if translation_file.exists():
            try:
                with open(translation_file, "r", encoding="utf-8") as f:
                    self.translations[language] = json.load(f)
            except Exception:
                # Fallback to English if translation file is corrupted
                if language != DEFAULT_LANGUAGE:
                    self.load_translations(DEFAULT_LANGUAGE)
        else:
            # Fallback to English if translation file doesn't exist
            if language != DEFAULT_LANGUAGE:
                self.load_translations(DEFAULT_LANGUAGE)

    def set_language(self, language: str) -> None:
        """Set current language"""
        if language in SUPPORTED_LANGUAGES:
            self.current_language = language
            self.load_translations(language)
            self.save_language_preference()

    def translate(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """Translate a key to current language with optional format arguments

        Supports nested keys like 'dashboard.connection' or 'common.ok'
        """
        translations = self.translations.get(self.current_language, {})

        # Handle nested keys (e.g., "dashboard.connection")
        keys = key.split(".")
        text = translations
        for k in keys:
            if isinstance(text, dict):
                text = text.get(k)
                if text is None:
                    break
            else:
                text = None
                break

        if text is None:
            text = default or key

        # Support format strings like {size}, {count}, etc.
        if kwargs and isinstance(text, str):
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass  # If formatting fails, return original text

        return text

    def is_rtl(self) -> bool:
        """Check if current language is RTL"""
        return self.current_language in RTL_LANGUAGES

    def get_language_name(self, language_code: str) -> str:
        """Get display name for a language code"""
        return SUPPORTED_LANGUAGES.get(language_code, {}).get("name", language_code)


# Global instance
_i18n_manager: Optional[I18nManager] = None


def get_i18n_manager() -> I18nManager:
    """Get global i18n manager instance"""
    global _i18n_manager
    if _i18n_manager is None:
        _i18n_manager = I18nManager()
    return _i18n_manager


def get_translator():
    """Get translator function"""
    manager = get_i18n_manager()
    return manager.translate
