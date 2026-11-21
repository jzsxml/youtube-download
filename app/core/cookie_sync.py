from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from yt_dlp.cookies import YDLLogger, YoutubeDLCookieJar, extract_cookies_from_browser

from app.config import APP_DATA_DIR, SESSION_COOKIE_FILE, SESSION_META_FILE
from app.core.errors import is_dpapi_error


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9?]*[a-zA-Z]", "", text).strip()


class CookieSyncError(RuntimeError):
    pass


class _QuietLogger(YDLLogger):
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, message, only_once=False):
        pass

    def error(self, message):
        pass


def session_cookie_path() -> Path:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_COOKIE_FILE


def has_session_cookies() -> bool:
    path = session_cookie_path()
    return path.is_file() and path.stat().st_size > 64


def read_session_meta() -> dict:
    if not SESSION_META_FILE.is_file():
        return {}
    try:
        return json.loads(SESSION_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_jar(jar: YoutubeDLCookieJar, browser: str) -> Path:
    out_path = session_cookie_path()
    out_jar = YoutubeDLCookieJar(str(out_path))
    kept = 0
    for cookie in jar:
        domain = cookie.domain or ""
        if "youtube.com" in domain or "google.com" in domain:
            out_jar.set_cookie(cookie)
            kept += 1
    if kept == 0:
        for cookie in jar:
            out_jar.set_cookie(cookie)
    out_jar.save(ignore_discard=True, ignore_expires=True)
    cookie_count = sum(1 for _ in out_jar)
    meta = {
        "browser": browser,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "cookie_count": cookie_count,
    }
    SESSION_META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out_path


def _dedupe_errors(errors: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in errors:
        norm = strip_ansi(line)
        key = norm[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def _failure_message(errors: list[str]) -> str:
    unique = _dedupe_errors(errors)
    if any(is_dpapi_error(e) for e in unique):
        return (
            "无法从 Chrome/Edge 读取 Cookie：Windows DPAPI 解密失败。\n"
            "常见原因：\n"
            "· 以「管理员」身份运行本程序（与日常浏览器的用户上下文不一致）\n"
            "· Chrome / Edge 127+ 启用了更强的 Cookie 加密\n\n"
            "本机请改用「在应用内登录 YouTube」——不读取系统浏览器数据库。\n"
            "「从浏览器导入」在你这台电脑上通常不可用。\n\n"
            "技术详情（已去重）：\n" + "\n".join(unique[:2])
        )
    return (
        "浏览器 Cookie 同步失败。\n"
        "1. 完全退出 Edge/Chrome 后再试\n"
        "2. 或改用「在应用内登录 YouTube」\n\n"
        "技术详情：\n" + "\n".join(unique[:4])
    )


def _extract_readonly_chromium(browser: str) -> YoutubeDLCookieJar:
    from yt_dlp.cookies import (
        _find_files,
        _get_chromium_based_browser_settings,
        _get_column_names,
        _newest,
        _process_chrome_cookie,
        get_cookie_decryptor,
    )

    logger = _QuietLogger()
    config = _get_chromium_based_browser_settings(browser)
    db_path = _newest(list(_find_files(config["browser_dir"], "Cookies", logger)))
    if not db_path:
        raise FileNotFoundError(f"未找到 {browser} Cookie 数据库")

    uri = "file:///" + db_path.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()
    meta_version = int(
        cursor.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0]
    )
    decryptor = get_cookie_decryptor(
        config["browser_dir"],
        config["keyring_name"],
        logger,
        meta_version=meta_version,
    )
    cursor.connection.text_factory = bytes
    colnames = _get_column_names(cursor, "cookies")
    secure_col = "is_secure" if "is_secure" in colnames else "secure"
    cursor.execute(
        f"SELECT host_key, name, value, encrypted_value, path, expires_utc, {secure_col} FROM cookies"
    )
    jar = YoutubeDLCookieJar()
    for row in cursor.fetchall():
        _, cookie = _process_chrome_cookie(decryptor, *row)
        if cookie:
            jar.set_cookie(cookie)
    conn.close()
    return jar


def _browser_running(browser: str) -> bool:
    names = {
        "edge": ("msedge.exe",),
        "chrome": ("chrome.exe",),
    }.get(browser, ())
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        text = out.stdout.lower()
        return any(n in text for n in names)
    except (OSError, subprocess.TimeoutExpired):
        return False


def sync_from_browser(browser: str) -> Path:
    browser = browser.lower()
    if browser not in ("edge", "chrome", "chromium", "brave", "firefox"):
        raise CookieSyncError(f"不支持的浏览器: {browser}")

    errors: list[str] = []

    if _browser_running(browser):
        errors.append(f"{browser} 仍在运行，无法复制 Cookie 数据库。")
        raise CookieSyncError(_failure_message(errors))

    try:
        jar = extract_cookies_from_browser(browser, profile=None)
        if sum(1 for _ in jar):
            return _save_jar(jar, browser)
        errors.append("直接读取: 未解析到任何 Cookie")
    except Exception as e:
        err = strip_ansi(str(e))
        errors.append(f"直接读取: {err}")
        if is_dpapi_error(err):
            raise CookieSyncError(_failure_message(errors))

    if browser == "firefox":
        raise CookieSyncError(_failure_message(errors))

    try:
        jar = _extract_readonly_chromium(browser)
        if sum(1 for _ in jar):
            return _save_jar(jar, browser)
        errors.append("只读数据库: 未解析到任何 Cookie")
    except Exception as e:
        err = strip_ansi(str(e))
        errors.append(f"只读数据库: {err}")

    raise CookieSyncError(_failure_message(errors))