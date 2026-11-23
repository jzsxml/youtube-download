"""Fetch the signed-in user's YouTube playlists via yt-dlp."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import yt_dlp

from app.core.auth import AuthConfig
from app.core.ydl_auth import library_extract_opts


@dataclass(frozen=True)
class PlaylistEntry:
    playlist_id: str
    title: str
    url: str
    video_count: int | None = None


@dataclass
class PlaylistFetchResult:
    entries: list[PlaylistEntry]
    warnings: list[str]


_BUILTIN = (
    PlaylistEntry("WL", "稍后观看", "https://www.youtube.com/playlist?list=WL"),
    PlaylistEntry("LL", "赞过的视频", "https://www.youtube.com/playlist?list=LL"),
)

# Prefer library feeds (cookie session). Channel /playlists tab often returns 401.
_FEED_URLS = (
    "https://www.youtube.com/feed/playlists",
    "https://www.youtube.com/feed/library",
)


class PlaylistLibraryError(RuntimeError):
    pass


def _playlist_url(list_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={list_id}"


def _parse_list_id(entry: dict) -> str | None:
    raw_id = entry.get("id") or entry.get("playlist_id")
    if raw_id and str(raw_id).startswith(("PL", "OL", "UU", "LL", "WL", "FL", "RD", "LM")):
        return str(raw_id)
    url = entry.get("url") or entry.get("webpage_url") or ""
    if "list=" in url:
        qs = parse_qs(urlparse(url).query)
        lid = qs.get("list", [None])[0]
        if lid:
            return lid
    return None


def _entries_from_info(info: dict | None) -> list[dict]:
    if not info:
        return []
    if info.get("_type") == "playlist":
        return [e for e in (info.get("entries") or []) if e]
    entries = info.get("entries")
    if isinstance(entries, list):
        return [e for e in entries if e]
    return []


def _entry_to_playlist(entry: dict) -> PlaylistEntry | None:
    list_id = _parse_list_id(entry)
    if not list_id:
        return None
    title = (entry.get("title") or list_id).strip()
    count = entry.get("playlist_count") or entry.get("n_entries")
    try:
        vc = int(count) if count is not None else None
    except (TypeError, ValueError):
        vc = None
    return PlaylistEntry(
        playlist_id=list_id,
        title=title,
        url=_playlist_url(list_id),
        video_count=vc,
    )


def _dedupe(entries: list[PlaylistEntry]) -> list[PlaylistEntry]:
    seen: set[str] = set()
    out: list[PlaylistEntry] = []
    for e in entries:
        if e.playlist_id in seen:
            continue
        seen.add(e.playlist_id)
        out.append(e)
    return out


def _normalize_channel_playlists_url(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    t = text.strip()
    if not t.startswith(("http://", "https://")):
        if t.startswith("@"):
            t = f"https://www.youtube.com/{t}"
        else:
            t = f"https://www.youtube.com/@{t.lstrip('@')}"
    t = t.rstrip("/")
    if not t.endswith("/playlists"):
        t = f"{t}/playlists"
    return t


def _is_auth_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "401" in s or "unauthorized" in s or "sign in" in s or "login" in s


def _extract(auth: AuthConfig, url: str, *, extract_flat: bool | str = True) -> dict | None:
    opts = library_extract_opts(auth, extract_flat=extract_flat)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _discover_channel_id(auth: AuthConfig) -> str | None:
    """Resolve logged-in user's channel id (avoids guessing @handle)."""
    for url in (
        "https://www.youtube.com/feed/you",
        "https://www.youtube.com/feed/account",
    ):
        try:
            info = _extract(auth, url, extract_flat=True)
        except Exception:
            continue
        if not info:
            continue
        cid = info.get("channel_id") or info.get("uploader_id")
        if cid and str(cid).startswith(("UC", "HC")):
            return str(cid)
        for raw in _entries_from_info(info):
            if not isinstance(raw, dict):
                continue
            cid = raw.get("channel_id") or raw.get("id")
            if cid and str(cid).startswith("UC"):
                return str(cid)
    return None


def _walk_collect_playlists(node, into: list[PlaylistEntry]) -> None:
    if isinstance(node, dict):
        pl = _entry_to_playlist(node)
        if pl:
            into.append(pl)
        for value in node.values():
            _walk_collect_playlists(value, into)
    elif isinstance(node, list):
        for item in node:
            _walk_collect_playlists(item, into)


def _merge_entries(info: dict | None, into: list[PlaylistEntry]) -> None:
    if not info:
        return
    before = len(into)
    _walk_collect_playlists(info, into)
    if len(into) > before:
        return
    for raw in _entries_from_info(info):
        if not isinstance(raw, dict):
            continue
        pl = _entry_to_playlist(raw)
        if pl:
            into.append(pl)


def fetch_user_playlists(
    auth: AuthConfig,
    *,
    channel_hint: str | None = None,
) -> PlaylistFetchResult:
    if not auth.cookies_will_be_sent():
        raise PlaylistLibraryError(
            "载入个人播放列表需要已登录 Cookie。\n"
            "请先在应用内登录并选择「已保存 Cookie 配置」或「当前会话」。"
        )

    collected: list[PlaylistEntry] = list(_BUILTIN)
    warnings: list[str] = []
    auth_failed = False

    for url in _FEED_URLS:
        try:
            info = _extract(auth, url, extract_flat=True)
            _merge_entries(info, collected)
        except Exception as e:
            if _is_auth_error(e):
                auth_failed = True
            warnings.append(f"跳过 {url}: {type(e).__name__}")

    channel_url = _normalize_channel_playlists_url(channel_hint)
    if channel_url is None:
        cid = _discover_channel_id(auth)
        if cid:
            channel_url = f"https://www.youtube.com/channel/{cid}/playlists"

    if channel_url:
        try:
            info = _extract(auth, channel_url, extract_flat="in_playlist")
            _merge_entries(info, collected)
        except Exception as e:
            if _is_auth_error(e):
                auth_failed = True
                warnings.append(
                    "频道播放列表页返回 401（Cookie 可能过期）。请重新登录；"
                    "也可在下方手动粘贴 playlist?list=PL… 链接。"
                )
            else:
                warnings.append(f"频道列表: {type(e).__name__}")

    result = _dedupe(collected)
    custom = len(result) - len(_BUILTIN)
    if custom == 0 and auth_failed:
        warnings.append(
            "未能拉取账号自建列表。请：① 应用内重新登录并「保存登录状态」；"
            "② 登录态选「已保存 Cookie 配置」；③ 或在浏览器打开 youtube.com/feed/playlists "
            "复制单个播放列表链接到主页下载。"
        )
    if len(result) == 0:
        result = list(_BUILTIN)
        warnings.append("列表异常为空，已恢复「稍后观看 / 赞过」。")
    return PlaylistFetchResult(entries=result, warnings=warnings)


def enrich_playlist_entry(entry: PlaylistEntry, auth: AuthConfig) -> PlaylistEntry:
    """Resolve real title and video count for a playlist URL (e.g. manual paste)."""
    try:
        info = _extract(auth, entry.url, extract_flat=True)
    except Exception:
        return entry
    if not info:
        return entry
    title = (info.get("title") or entry.title).strip()
    count = info.get("playlist_count") or info.get("n_entries")
    if count is None:
        entries = info.get("entries")
        if isinstance(entries, list):
            count = len([e for e in entries if e])
    try:
        vc = int(count) if count is not None else None
    except (TypeError, ValueError):
        vc = entry.video_count
    return PlaylistEntry(
        playlist_id=entry.playlist_id,
        title=title or entry.title,
        url=entry.url,
        video_count=vc if vc is not None else entry.video_count,
    )


def parse_playlist_url(text: str) -> PlaylistEntry | None:
    """Parse a pasted playlist URL or raw list=PL… id."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("PL") and len(text) >= 10:
        return PlaylistEntry(text, text, _playlist_url(text))
    if "list=" in text:
        qs = parse_qs(urlparse(text).query)
        lid = qs.get("list", [None])[0]
        if lid:
            title = lid
            return PlaylistEntry(lid, title, _playlist_url(lid))
    return None


# Backward-compatible helper for tests
def fetch_user_playlists_list(
    auth: AuthConfig,
    *,
    channel_hint: str | None = None,
) -> list[PlaylistEntry]:
    return fetch_user_playlists(auth, channel_hint=channel_hint).entries