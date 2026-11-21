import re
from urllib.parse import urlparse, parse_qs

_YT_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)


def normalize_youtube_url(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", text):
        return f"https://www.youtube.com/watch?v={text}"
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host == "youtu.be":
        if parsed.path.strip("/"):
            return f"https://www.youtube.com/watch?v={parsed.path.strip('/')}"
        return None
    if "youtube.com" not in host and host not in _YT_HOSTS:
        # allow youtube.com subdomains
        if not host.endswith("youtube.com"):
            return None
    if "watch" in parsed.path or "shorts" in parsed.path or "playlist" in parsed.path:
        return text.split("&list=")[0] if "watch" in parsed.path else text
    if parsed.path.startswith("/shorts/"):
        vid = parsed.path.split("/")[-1]
        return f"https://www.youtube.com/watch?v={vid}"
    if "v" in parse_qs(parsed.query):
        vid = parse_qs(parsed.query)["v"][0]
        return f"https://www.youtube.com/watch?v={vid}"
    return text if "youtube" in host else None


def should_expand_playlist(url: str, expand_enabled: bool) -> bool:
    """Only call yt-dlp playlist extract when URL is actually a playlist / has list=."""
    if not expand_enabled:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if "playlist" in parsed.path:
        return True
    qs = parse_qs(parsed.query)
    list_id = qs.get("list", [None])[0]
    if list_id:
        return True
    return False