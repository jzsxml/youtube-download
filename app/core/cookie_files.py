"""Validate and snapshot Netscape cookies.txt for yt-dlp (avoid read/write races)."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import APP_DATA_DIR

_NETSCAPE_MARKER = "# Netscape HTTP Cookie File"
_SNAPSHOT_DIR = APP_DATA_DIR / "cookie_snapshots"


def netscape_cookie_looks_valid(text: str) -> bool:
    if not text or _NETSCAPE_MARKER not in text[:256]:
        return False
    lines = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            return False
        lines += 1
    return lines > 0


def snapshot_cookie_file(path: Path) -> Path:
    """Return a stable snapshot path for yt-dlp (mtime-keyed cache)."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    if not netscape_cookie_looks_valid(text):
        raise ValueError(
            f"'{resolved}' 不是有效的 Netscape cookies.txt。"
            "请重新「在应用内登录」并保存，或从浏览器导出 JSON 后导入。"
        )
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = _SNAPSHOT_DIR / f"{resolved.stem}_{resolved.stat().st_mtime_ns}.txt"
    if not dest.is_file() or dest.stat().st_size != resolved.stat().st_size:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, dest)
    return dest


def atomic_copy_cookie_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8", errors="replace")
    if not netscape_cookie_looks_valid(text):
        raise ValueError("源 Cookie 文件无效，无法保存到配置。")
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)