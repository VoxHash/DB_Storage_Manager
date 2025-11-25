"""
Internationalization (i18n) support for DB Storage Manager
"""

from .manager import I18nManager, get_translator
from .languages import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

__all__ = ["I18nManager", "get_translator", "SUPPORTED_LANGUAGES", "DEFAULT_LANGUAGE"]

