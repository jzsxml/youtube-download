"""Resolve bundled vs development paths (PyInstaller sys._MEIPASS)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def ui_dir() -> Path:
    if is_frozen():
        return bundle_root() / "app" / "ui"
    return Path(__file__).resolve().parent / "ui"


def resources_dir() -> Path:
    if is_frozen():
        return bundle_root() / "app" / "resources"
    return Path(__file__).resolve().parent / "resources"