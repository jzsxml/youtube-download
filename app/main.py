import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def _load_styles(app: QApplication) -> None:
    qss_path = Path(__file__).resolve().parent / "ui" / "styles.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def _apply_readable_palette(app: QApplication) -> None:
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#f2f6fb"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9eb2cc"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e2a40"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Downloader")
    _apply_readable_palette(app)
    _load_styles(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())