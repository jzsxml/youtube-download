"""Application icon: vector draw + optional app/resources/app.ico on disk."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
ICO_PATH = RESOURCES_DIR / "app.ico"

_APP_ID = "YouTubeDownloader.Desktop.1"


def configure_windows_taskbar() -> None:
    """Show custom .ico on the taskbar when running from python.exe (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except OSError:
        pass


def _draw_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    m = max(2, size // 10)
    bg = QColor("#e62117")
    p.setBrush(bg)
    p.setPen(QPen(QColor("#8f1210"), max(1, size // 64)))
    p.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, size * 0.18, size * 0.18)

    play = QPolygonF(
        [
            QPointF(size * 0.38, size * 0.30),
            QPointF(size * 0.38, size * 0.70),
            QPointF(size * 0.72, size * 0.50),
        ]
    )
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(play)

    arrow_w = size * 0.22
    cx = size * 0.50
    y0 = size * 0.76
    y1 = size * 0.88
    p.setPen(QPen(QColor("#ffffff"), max(2, size // 18), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(cx, y0), QPointF(cx, y1))
    p.drawLine(QPointF(cx - arrow_w / 2, y1 - arrow_w * 0.35), QPointF(cx, y1))
    p.drawLine(QPointF(cx + arrow_w / 2, y1 - arrow_w * 0.35), QPointF(cx, y1))

    p.end()
    return pm


def build_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw_pixmap(size))
    return icon


def load_app_icon() -> QIcon:
    if ICO_PATH.is_file():
        from_file = QIcon(str(ICO_PATH))
        if not from_file.isNull():
            return from_file
    return build_app_icon()


def write_app_ico(path: Path | None = None) -> Path:
    """Write multi-size icon file (run scripts/build_app_icon.py)."""
    target = path or ICO_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    pm = _draw_pixmap(256)
    if not pm.save(str(target), "ICO"):
        raise OSError(f"Failed to write icon: {target}")
    return target