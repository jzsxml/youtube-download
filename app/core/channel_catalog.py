"""Fetch paginated videos / Shorts from a YouTube channel tab via yt-dlp."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote, urlparse

import yt_dlp

from app.core.auth import AuthConfig
from app.core.ydl_auth import library_extract_opts

PAGE_SIZE = 100

_TAB_SUFFIXES = frozenset(
    {
        "videos",
        "shorts",
        "streams",
        "playlists",
        "featured",
        "about",
        "community",
        "channels",
        "search",
    }
)


class ChannelTab(str, Enum):
    VIDEOS = "videos"
    SHORTS = "shorts"


class ChannelCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChannelVideoEntry:
    video_id: str
    title: str
    url: str
    duration: int | None = None
    is_short: bool = False


@dataclass
class ChannelPageResult:
    entries: list[ChannelVideoEntry]
    page: int
    page_size: int
    has_next: bool
    tab: ChannelTab
    source_url: str


def page_to_range(page: int, page_size: int = PAGE_SIZE) -> tuple[int, int]:
    if page < 1:
        page = 1
    start = (page - 1) * page_size + 1
    end = page * page_size
    return start, end


def normalize_channel_base(text: str) -> str | None:
    """Normalize @handle / channel /c/… URL to base without tab suffix."""
    text = text.strip()
    if not text:
        return None
    if not text.startswith(("http://", "https://")):
        if text.startswith("@"):
            text = f"https://www.youtube.com/{text}"
        elif text.startswith("UC") and len(text) >= 22:
            text = f"https://www.youtube.com/channel/{text}"
        else:
            text = f"https://www.youtube.com/@{text.lstrip('@')}"
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if "youtube.com" not in host and not host.endswith("youtube.com"):
        return None
    path = unquote(parsed.path or "").strip("/")
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if parts and parts[-1].lower() in _TAB_SUFFIXES:
        parts.pop()
    if not parts:
        return None
    head = parts[0].lower()
    if head in ("channel", "c", "user"):
        if len(parts) < 2:
            return None
        slug = "/".join(parts[:2])
    elif head.startswith("@"):
        slug = parts[0]
    else:
        slug = "/".join(parts)
    return f"https://www.youtube.com/{slug}"


def channel_tab_url(base: str, tab: ChannelTab) -> str:
    return f"{base.rstrip('/')}/{tab.value}"


def _format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_entry_label(entry: ChannelVideoEntry) -> str:
    dur = _format_duration(entry.duration)
    tag = " [Short]" if entry.is_short else ""
    if dur:
        return f"{entry.title}{tag}  ({dur})"
    return f"{entry.title}{tag}"


def _entry_from_raw(raw: dict, *, is_short: bool) -> ChannelVideoEntry | None:
    if not isinstance(raw, dict):
        return None
    vid = raw.get("id")
    if not vid or len(str(vid)) != 11:
        url = raw.get("url") or raw.get("webpage_url") or ""
        if "v=" in url:
            from urllib.parse import parse_qs, urlparse

            vid = parse_qs(urlparse(url).query).get("v", [None])[0]
        elif "/shorts/" in url:
            vid = url.rstrip("/").split("/shorts/")[-1].split("?")[0]
    if not vid or len(str(vid)) != 11:
        return None
    title = (raw.get("title") or vid).strip()
    duration = raw.get("duration")
    try:
        dur = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        dur = None
    watch = f"https://www.youtube.com/watch?v={vid}"
    return ChannelVideoEntry(
        video_id=str(vid),
        title=title,
        url=watch,
        duration=dur,
        is_short=is_short,
    )


def fetch_channel_page(
    auth: AuthConfig,
    channel_text: str,
    tab: ChannelTab,
    page: int,
    *,
    page_size: int = PAGE_SIZE,
) -> ChannelPageResult:
    base = normalize_channel_base(channel_text)
    if not base:
        raise ChannelCatalogError(
            "无法识别频道地址。请粘贴 @名称、频道主页或 /channel/UC… 链接。"
        )
    if page < 1:
        page = 1
    url = channel_tab_url(base, tab)
    start, end = page_to_range(page, page_size)
    opts = library_extract_opts(auth, extract_flat="in_playlist")
    opts["playliststart"] = start
    opts["playlistend"] = end
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise ChannelCatalogError(str(e)) from e
    if not info:
        raise ChannelCatalogError(f"未能读取频道页面: {url}")
    raw_entries = info.get("entries") or []
    entries_list = list(raw_entries) if not isinstance(raw_entries, list) else raw_entries
    is_short = tab == ChannelTab.SHORTS
    entries: list[ChannelVideoEntry] = []
    for raw in entries_list:
        if raw is None:
            continue
        ent = _entry_from_raw(raw, is_short=is_short)
        if ent:
            entries.append(ent)
    has_next = len(entries) >= page_size
    return ChannelPageResult(
        entries=entries,
        page=page,
        page_size=page_size,
        has_next=has_next,
        tab=tab,
        source_url=url,
    )


def filter_entries_by_title(
    entries: list[ChannelVideoEntry], keyword: str
) -> list[ChannelVideoEntry]:
    kw = keyword.strip().casefold()
    if not kw:
        return list(entries)
    return [e for e in entries if kw in e.title.casefold()]