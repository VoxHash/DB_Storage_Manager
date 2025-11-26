"""
Theme definitions
"""

THEMES = {
    "light": {
        "name": "Light",
        "colors": {
            "background": "#FFFFFF",
            "surface": "#F5F5F5",
            "primary": "#2196F3",
            "secondary": "#FF9800",
            "text": "#212121",
            "text_secondary": "#757575",
            "border": "#E0E0E0",
            "success": "#4CAF50",
            "error": "#F44336",
            "warning": "#FF9800",
            "info": "#2196F3",
        },
        "glassmorphism": {
            "background": "rgba(255, 255, 255, 0.7)",
            "border": "rgba(255, 255, 255, 0.18)",
            "backdrop_blur": "10px",
        },
    },
    "dark": {
        "name": "Dark",
        "colors": {
            "background": "#121212",
            "surface": "#1E1E1E",
            "primary": "#64B5F6",
            "secondary": "#FFB74D",
            "text": "#FFFFFF",
            "text_secondary": "#B0B0B0",
            "border": "#333333",
            "success": "#81C784",
            "error": "#E57373",
            "warning": "#FFB74D",
            "info": "#64B5F6",
        },
        "glassmorphism": {
            "background": "rgba(30, 30, 30, 0.7)",
            "border": "rgba(255, 255, 255, 0.1)",
            "backdrop_blur": "10px",
        },
    },
    "dracula": {
        "name": "Dracula",
        "colors": {
            "background": "#282A36",
            "surface": "#44475A",
            "primary": "#BD93F9",
            "secondary": "#FF79C6",
            "text": "#F8F8F2",
            "text_secondary": "#6272A4",
            "border": "#6272A4",
            "success": "#50FA7B",
            "error": "#FF5555",
            "warning": "#F1FA8C",
            "info": "#8BE9FD",
        },
        "glassmorphism": {
            "background": "rgba(68, 71, 90, 0.7)",
            "border": "rgba(189, 147, 249, 0.2)",
            "backdrop_blur": "10px",
        },
    },
}

DEFAULT_THEME = "dark"
