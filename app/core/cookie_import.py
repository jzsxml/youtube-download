from __future__ import annotations

import http.cookiejar
import json
from datetime import datetime, timezone
from pathlib import Path

from yt_dlp.cookies import YoutubeDLCookieJar

from app.config import SESSION_META_FILE
from app.core.cookie_sync import session_cookie_path


class CookieImportError(ValueError):
    pass


def _normalize_domain(domain: str, host_only: bool = False) -> str:
    domain = (domain or "").strip()
    if not domain:
        return ""
    if domain.startswith("http"):
        domain = domain.split("/")[2]
    if not host_only and domain and not domain.startswith("."):
        if domain.count(".") >= 1:
            domain = "." + domain.lstrip(".")
    return domain


def _expiry_seconds(item: dict) -> float | None:
    for key in ("expirationDate", "expires", "expiration", "expire", "expiry"):
        raw = item.get(key)
        if raw in (None, "", 0, False):
            continue
        if isinstance(raw, str) and raw.isdigit():
            raw = int(raw)
        if isinstance(raw, (int, float)):
            v = float(raw)
            if v > 1e12:
                v /= 1000.0
            return v
    if item.get("session") is True:
        return None
    return None


def _item_to_cookie(item: dict) -> http.cookiejar.Cookie | None:
    name = item.get("name") or item.get("Name")
    value = item.get("value") or item.get("Value")
    if value is None:
        value = ""
    domain = (
        item.get("domain")
        or item.get("host")
        or item.get("Domain")
        or item.get("Host")
    )
    if not name or not domain:
        return None

    host_only = bool(item.get("hostOnly") or item.get("host_only"))
    domain = _normalize_domain(str(domain), host_only=host_only)
    path = item.get("path") or item.get("Path") or "/"
    secure = bool(item.get("secure") or item.get("Secure"))
    expires = _expiry_seconds(item)
    rest: dict = {}
    if item.get("httpOnly") or item.get("HttpOnly"):
        rest["HttpOnly"] = None

    return http.cookiejar.Cookie(
        version=0,
        name=str(name),
        value=str(value),
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=str(path),
        path_specified=bool(path),
        secure=secure,
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest=rest,
    )


def _unwrap_json_root(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("cookies", "data", "items", "cookie"):
            if isinstance(data.get(key), list):
                return data[key]
    raise CookieImportError("不支持的 JSON 结构，需要 Cookie 对象数组或 { \"cookies\": [...] }")


def import_json_cookies(path: Path, save_as_session: bool = True) -> tuple[Path, int]:
    """Import browser-exported JSON cookies; save as Netscape cookies.txt for yt-dlp."""
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise CookieImportError("JSON 文件为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CookieImportError(f"JSON 解析失败: {e}") from e

    rows = _unwrap_json_root(data)
    out_path = session_cookie_path() if save_as_session else path.with_suffix(".txt")
    jar = YoutubeDLCookieJar(str(out_path))

    kept_yt = 0
    kept_all = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        cookie = _item_to_cookie(item)
        if not cookie:
            continue
        domain = cookie.domain or ""
        if "youtube.com" in domain or "google.com" in domain:
            jar.set_cookie(cookie)
            kept_yt += 1
        kept_all += 1

    if kept_yt == 0:
        jar = YoutubeDLCookieJar(str(out_path))
        for item in rows:
            if not isinstance(item, dict):
                continue
            cookie = _item_to_cookie(item)
            if cookie:
                jar.set_cookie(cookie)
        kept_yt = sum(1 for _ in jar)

    if kept_yt == 0:
        raise CookieImportError(
            "未能从 JSON 中解析任何 Cookie，请确认是浏览器导出的 Cookie 列表"
        )

    jar.save(ignore_discard=True, ignore_expires=True)
    count = sum(1 for _ in jar)

    if save_as_session:
        SESSION_META_FILE.write_text(
            json.dumps(
                {
                    "browser": f"json:{path.name}",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "cookie_count": count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return out_path, count