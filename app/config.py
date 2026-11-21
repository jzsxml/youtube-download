import os
from pathlib import Path

APP_NAME = "YouTube Downloader"
APP_VERSION = "0.1.0"

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YouTube"
DEFAULT_MAX_WORKERS = 3
# Max UI table refresh rate per download task (seconds)
PROGRESS_UI_INTERVAL = 0.25

APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "YouTubeDownloader"
SESSION_COOKIE_FILE = APP_DATA_DIR / "youtube_cookies.txt"
SESSION_META_FILE = APP_DATA_DIR / "session_meta.json"

# Fallback chains (/) so yt-dlp does not fail when a specific merge is unavailable
FORMAT_PRESETS = {
    "best": (
        "最佳画质",
        "bestvideo*+bestaudio/bestvideo+bestaudio/best",
    ),
    "1080": (
        "1080p 及以下",
        "bestvideo[height<=1080]*+bestaudio/bestvideo[height<=1080]+bestaudio/"
        "best[height<=1080]/bestvideo*+bestaudio/best",
    ),
    "720": (
        "720p 及以下",
        "bestvideo[height<=720]*+bestaudio/bestvideo[height<=720]+bestaudio/"
        "best[height<=720]/bestvideo*+bestaudio/best",
    ),
    "audio": ("仅音频", "bestaudio/bestaudio/best"),
}

FORMAT_FALLBACK = "bestvideo*+bestaudio/best"