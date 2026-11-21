"""Path safety helpers for opening user-adjacent files on Windows."""

from __future__ import annotations

from pathlib import Path


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_safe_output_file(path: str | Path, output_dir: Path) -> bool:
    """Only open files under the configured download directory."""
    if not path:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    out = output_dir.resolve()
    try:
        p.resolve().relative_to(out)
        return True
    except (ValueError, OSError):
        return False