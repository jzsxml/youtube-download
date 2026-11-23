from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.core.cookie_profiles import _read_settings, _write_settings
from app.paths import ui_dir

THEME_DIR = ui_dir() / "themes"


class ThemeId(str, Enum):
    DARK = "dark"
    LIGHT = "light"


STATUS_COLORS = {
    ThemeId.DARK: {
        "default": "#f0f4fa",
        "id": "#c8daf0",
        "speed": "#d8e4f4",
        "error": "#ff8a8a",
        "finished": "#7dffb8",
        "downloading": "#7ae8ff",
        "queued": "#d4dce8",
        "merging": "#ffd966",
        "paused": "#ffb86c",
        "cancelled": "#b0bccf",
    },
    ThemeId.LIGHT: {
        "default": "#1a2332",
        "id": "#3d5a80",
        "speed": "#2d4a6e",
        "error": "#c0392b",
        "finished": "#1e7a4a",
        "downloading": "#0d7ea8",
        "queued": "#5a6b7c",
        "merging": "#b8860b",
        "paused": "#c46b1c",
        "cancelled": "#6b7c8f",
    },
}


def get_saved_theme() -> ThemeId:
    raw = _read_settings().get("ui_theme", "dark")
    try:
        return ThemeId(raw)
    except ValueError:
        return ThemeId.DARK


def save_theme(theme: ThemeId) -> None:
    data = _read_settings()
    data["ui_theme"] = theme.value
    _write_settings(data)


def apply_theme(app: QApplication, theme: ThemeId) -> None:
    qss_path = THEME_DIR / f"{theme.value}.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    else:
        legacy = ui_dir() / "styles.qss"
        if legacy.is_file():
            app.setStyleSheet(legacy.read_text(encoding="utf-8"))

    pal = app.palette()
    if theme == ThemeId.LIGHT:
        pal.setColor(QPalette.ColorRole.Window, QColor("#eef1f6"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f4f7fb"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#1a2332"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#1a2332"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1a2332"))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b7c8f"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#1a2332"))
    else:
        pal.setColor(QPalette.ColorRole.Window, QColor("#0a0e17"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#121a2a"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#171f30"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#f2f6fb"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9eb2cc"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e2a40"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)