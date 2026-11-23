"""Shared yt-dlp options for authenticated YouTube requests."""

from __future__ import annotations

from app.core.auth import AuthConfig


class _YdlQuietLogger:
    def debug(self, msg) -> None:
        pass

    def info(self, msg) -> None:
        pass

    def warning(self, msg) -> None:
        pass

    def error(self, msg) -> None:
        pass


def apply_auth_youtube_opts(auth: AuthConfig, opts: dict) -> dict:
    auth.apply_to_ydl_opts(opts)
    opts.setdefault("extractor_args", {}).setdefault(
        "youtube",
        {},
    )
    yt_args = opts["extractor_args"]["youtube"]
    yt_args.setdefault("player_client", ["web", "mweb"])
    yt_args.setdefault("player_skip", ["configs"])
    return opts


def library_extract_opts(auth: AuthConfig, *, extract_flat: bool | str = True) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "logger": _YdlQuietLogger(),
        "extract_flat": extract_flat,
    }
    apply_auth_youtube_opts(auth, opts)
    return opts