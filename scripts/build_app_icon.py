"""Generate app/resources/app.ico. Requires PySide6 (use project venv)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from app.ui.app_icon import ICO_PATH, write_app_ico


def main() -> None:
    app = QApplication([])
    path = write_app_ico()
    print(f"Wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()