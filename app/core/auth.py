from dataclasses import dataclass
from pathlib import Path

from app.config import SESSION_COOKIE_FILE
from app.core.cookie_import import import_json_cookies
from app.core.cookie_profiles import get_active_profile_id, profile_cookie_path
from app.core.cookie_sync import has_session_cookies

_JSON_CONVERT_CACHE: dict[str, str] = {}


@dataclass
class AuthConfig:
    """How to pass login state to yt-dlp."""

    mode: str = "none"  # none | profile | session | edge | chrome | cookiefile
    cookie_path: str | None = None
    profile_id: str | None = None
    prefer_session_file: bool = True

    def _session_path(self) -> Path | None:
        if self.mode == "profile":
            pid = self.profile_id or get_active_profile_id()
            path = profile_cookie_path(pid)
            if path:
                return path
        if has_session_cookies():
            return SESSION_COOKIE_FILE
        return None

    def _custom_file(self) -> Path | None:
        if not self.cookie_path:
            return None
        path = Path(self.cookie_path)
        if not path.is_file():
            return None
        if path.suffix.lower() == ".json":
            cache_key = f"{path.resolve()}:{path.stat().st_mtime_ns}"
            cached = _JSON_CONVERT_CACHE.get(cache_key)
            if cached and Path(cached).is_file():
                return Path(cached)
            out_path, _ = import_json_cookies(path, save_as_session=False)
            _JSON_CONVERT_CACHE[cache_key] = str(out_path)
            return out_path
        return path

    def cookies_will_be_sent(self) -> bool:
        probe: dict = {}
        self.apply_to_ydl_opts(probe)
        return "cookiefile" in probe or "cookiesfrombrowser" in probe

    def apply_to_ydl_opts(self, opts: dict) -> dict:
        opts.pop("cookiesfrombrowser", None)
        opts.pop("cookiefile", None)

        if self.mode == "none":
            return opts

        if self.mode == "cookiefile":
            path = self._custom_file()
            if path:
                opts["cookiefile"] = str(path)
            return opts

        if self.mode in ("session", "profile"):
            path = self._session_path()
            if path:
                opts["cookiefile"] = str(path)
            return opts

        if self.mode in ("edge", "chrome"):
            if self.prefer_session_file:
                meta_path = self._session_path()
                if meta_path:
                    opts["cookiefile"] = str(meta_path)
                    return opts
            opts["cookiesfrombrowser"] = (self.mode,)
            return opts

        return opts