"""Locate ffmpeg for yt-dlp (bundled next to exe, vendor/, or PATH)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.paths import is_frozen


def application_dir() -> Path:
    """Directory containing the running app (exe folder when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _dir_has_ffmpeg(folder: Path) -> bool:
    return (folder / "ffmpeg.exe").is_file()


def resolve_ffmpeg_dir() -> Path | None:
    base = application_dir()
    for candidate in (
        base / "ffmpeg",
        base / "vendor" / "ffmpeg",
        base,
    ):
        if _dir_has_ffmpeg(candidate):
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return Path(found).resolve().parent
    return None


def ffmpeg_available() -> bool:
    return resolve_ffmpeg_dir() is not None


def apply_ffmpeg_to_opts(opts: dict) -> None:
    folder = resolve_ffmpeg_dir()
    if folder is not None:
        opts["ffmpeg_location"] = str(folder)


def ffmpeg_status_message() -> str:
    folder = resolve_ffmpeg_dir()
    if folder is None:
        return "未找到 ffmpeg：无法合并高清音视频或导出 mp3。"
    if _is_bundled_dir(folder):
        return f"ffmpeg（内置）: {folder}"
    return f"ffmpeg（系统）: {folder}"


def _is_bundled_dir(folder: Path) -> bool:
    base = application_dir()
    return folder in (base / "ffmpeg", base / "vendor" / "ffmpeg") or (
        folder == base and (base / "ffmpeg.exe").is_file()
    )