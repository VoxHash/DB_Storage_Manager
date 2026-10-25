"""
Theme definitions — design tokens for the desktop shell.

Token naming follows a page/ink/muted/line/soft/accent model (adapted from
open design-system patterns) mapped onto DB Storage Manager surfaces.
"""

THEMES = {
    "light": {
        "name": "Light",
        "colors": {
            "background": "#F4F6F8",
            "surface": "#FFFFFF",
            "surface_elevated": "#FFFFFF",
            "primary": "#294F82",
            "primary_hover": "#1F3D66",
            "secondary": "#5B6570",
            "text": "#20252B",
            "text_secondary": "#5B6570",
            "border": "#E0E5E9",
            "success": "#2E7D32",
            "error": "#C62828",
            "warning": "#EF6C00",
            "info": "#294F82",
            "sidebar_bg": "#EEF1F4",
            "sidebar_hover": "#E4E9EE",
            "sidebar_active": "#E8EEF6",
            "content_bg": "#F4F6F8",
            "row_alt": "#F7F9FB",
            "input_bg": "#FFFFFF",
            "selection": "#DCE8F6",
            "on_primary": "#FFFFFF",
        },
        "glassmorphism": {
            "background": "rgba(255, 255, 255, 0.92)",
            "border": "rgba(224, 229, 233, 0.95)",
            "backdrop_blur": "10px",
        },
    },
    "dark": {
        "name": "Atmospheric",
        "colors": {
            "background": "#0B0F14",
            "surface": "#121820",
            "surface_elevated": "#1A2330",
            "primary": "#2DD4BF",
            "primary_hover": "#14B8A6",
            "secondary": "#94A3B8",
            "text": "#E8EEF4",
            "text_secondary": "#94A3B8",
            "border": "#243044",
            "success": "#34D399",
            "error": "#F87171",
            "warning": "#FBBF24",
            "info": "#38BDF8",
            "sidebar_bg": "#0A1018",
            "sidebar_hover": "#152033",
            "sidebar_active": "#1A2A3C",
            "content_bg": "#0E141C",
            "row_alt": "#101820",
            "input_bg": "#152033",
            "selection": "#1E3A4A",
            "on_primary": "#042F2E",
        },
        "glassmorphism": {
            "background": "rgba(18, 24, 32, 0.92)",
            "border": "rgba(36, 48, 68, 0.95)",
            "backdrop_blur": "10px",
        },
    },
    "dracula": {
        "name": "Dracula",
        "colors": {
            "background": "#1E1F29",
            "surface": "#282A36",
            "surface_elevated": "#313244",
            "primary": "#BD93F9",
            "primary_hover": "#A78BFA",
            "secondary": "#FF79C6",
            "text": "#F8F8F2",
            "text_secondary": "#A6ADC8",
            "border": "#45475A",
            "success": "#50FA7B",
            "error": "#FF5555",
            "warning": "#F1FA8C",
            "info": "#8BE9FD",
            "sidebar_bg": "#181825",
            "sidebar_hover": "#242636",
            "sidebar_active": "#313244",
            "content_bg": "#1E1F29",
            "row_alt": "#222433",
            "input_bg": "#282A36",
            "selection": "#313244",
            "on_primary": "#1E1F29",
        },
        "glassmorphism": {
            "background": "rgba(40, 42, 54, 0.92)",
            "border": "rgba(69, 71, 90, 0.95)",
            "backdrop_blur": "10px",
        },
    },
}

DEFAULT_THEME = "dark"
