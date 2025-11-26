"""
Supported languages configuration
"""

SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "native": "English", "rtl": False},
    "ru": {"name": "Russian", "native": "Русский", "rtl": False},
    "pt": {"name": "Portuguese", "native": "Português", "rtl": False},
    "es": {"name": "Spanish", "native": "Español", "rtl": False},
    "et": {"name": "Estonian", "native": "Eesti", "rtl": False},
    "fr": {"name": "French", "native": "Français", "rtl": False},
    "de": {"name": "German", "native": "Deutsch", "rtl": False},
    "ja": {"name": "Japanese", "native": "日本語", "rtl": False},
    "zh": {"name": "Chinese", "native": "中文", "rtl": False},
    "ko": {"name": "Korean", "native": "한국어", "rtl": False},
    "id": {"name": "Indonesian", "native": "Bahasa Indonesia", "rtl": False},
}

DEFAULT_LANGUAGE = "en"

# RTL languages (for future support)
RTL_LANGUAGES = {"ar", "he", "fa", "ur"}  # None of our current languages, but prepared
