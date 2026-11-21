import sys

from PySide6.QtWidgets import QApplication

from app.ui.app_icon import configure_windows_taskbar, load_app_icon
from app.ui.main_window import MainWindow
from app.ui.themes import ThemeId, apply_theme, get_saved_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Downloader")
    app.setApplicationDisplayName("YouTube Downloader")
    configure_windows_taskbar()
    icon = load_app_icon()
    app.setWindowIcon(icon)
    theme = get_saved_theme()
    apply_theme(app, theme)
    window = MainWindow(initial_theme=theme, app_icon=icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())