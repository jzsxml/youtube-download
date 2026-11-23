from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp

import shutil

from app.config import FORMAT_FALLBACK, FORMAT_PRESETS
from app.core.auth import AuthConfig
from app.core.cookie_sync import strip_ansi
from app.core.errors import is_cookie_infrastructure_error, is_format_unavailable
from app.core.ffmpeg_locator import apply_ffmpeg_to_opts
from app.core.ydl_auth import _YdlQuietLogger, apply_auth_youtube_opts


ProgressCallback = Callable[[dict], None]


def build_ydl_opts(
    output_dir: Path,
    format_key: str,
    auth: AuthConfig,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict:
    fmt = FORMAT_PRESETS.get(format_key, FORMAT_PRESETS["best"])[1]
    opts: dict = {
        "outtmpl": str(output_dir / "%(title).100s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "noplaylist": False,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [],
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "nopart": False,
        "concurrent_fragment_downloads": 3,
        "noprogress": True,
        "logger": _YdlQuietLogger(),
    }
    apply_ffmpeg_to_opts(opts)
    if shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
        opts["remote_components"] = ["ejs:github"]
    if format_key == "audio":
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

    auth.apply_to_ydl_opts(opts)

    def hook(d: dict) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        if on_progress:
            on_progress(d)

    opts["progress_hooks"].append(hook)
    return opts


def build_ydl_opts_with_format(
    output_dir: Path,
    format_key: str,
    auth: AuthConfig,
    format_override: str | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict:
    opts = build_ydl_opts(
        output_dir, format_key, auth, on_progress=on_progress, cancel_event=cancel_event
    )
    if format_override:
        opts["format"] = format_override
    return opts


def _extract_playlist_info(url: str, auth: AuthConfig):
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    apply_auth_youtube_opts(auth, opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def extract_urls_from_playlist(url: str, auth: AuthConfig) -> list[str]:
    """Expand playlist to individual watch URLs when possible."""
    try:
        info = _extract_playlist_info(url, auth)
    except Exception as e:
        err = strip_ansi(str(e))
        if auth.mode != "none" and (
            is_cookie_infrastructure_error(err)
            or is_format_unavailable(err)
            or "please sign in" in err.lower()
        ):
            info = _extract_playlist_info(url, AuthConfig(mode="none"))
        else:
            raise
    if info is None:
        return [url]
    if info.get("_type") == "playlist":
        raw_entries = info.get("entries") or []
        entries = list(raw_entries) if not isinstance(raw_entries, list) else raw_entries
        urls: list[str] = []
        for e in entries:
            if e is None:
                continue
            if e.get("url"):
                urls.append(e["url"])
            elif e.get("id"):
                urls.append(f"https://www.youtube.com/watch?v={e['id']}")
        if urls:
            return urls
        pc = info.get("playlist_count") or info.get("n_entries")
        if pc and int(pc) > 0:
            raise RuntimeError(
                f"播放列表约有 {pc} 个视频，但未能展开条目。"
                "请检查 Cookie / 登录态，或把链接贴到主页地址栏单独下载。"
            )
        return [url]
    return [url]