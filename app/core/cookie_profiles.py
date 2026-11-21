from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import APP_DATA_DIR, SESSION_COOKIE_FILE, SESSION_META_FILE

PROFILES_INDEX = APP_DATA_DIR / "cookie_profiles.json"
APP_SETTINGS = APP_DATA_DIR / "app_settings.json"
PROFILES_DIR = APP_DATA_DIR / "cookie_profiles"


@dataclass
class CookieProfile:
    profile_id: str
    name: str
    created_at: str
    source: str = ""
    cookie_count: int = 0

    @property
    def cookie_file(self) -> Path:
        return PROFILES_DIR / self.profile_id / "cookies.txt"

    @property
    def meta_file(self) -> Path:
        return PROFILES_DIR / self.profile_id / "meta.json"


def _ensure_dirs() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict]:
    _ensure_dirs()
    if not PROFILES_INDEX.is_file():
        return []
    try:
        data = json.loads(PROFILES_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(rows: list[dict]) -> None:
    _ensure_dirs()
    PROFILES_INDEX.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_settings() -> dict:
    if not APP_SETTINGS.is_file():
        return {}
    try:
        return json.loads(APP_SETTINGS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_settings(data: dict) -> None:
    _ensure_dirs()
    APP_SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def migrate_legacy_session() -> None:
    """Move single-session file into profile store if needed."""
    if _load_index():
        return
    if not SESSION_COOKIE_FILE.is_file() or SESSION_COOKIE_FILE.stat().st_size < 64:
        return
    meta = {}
    if SESSION_META_FILE.is_file():
        try:
            meta = json.loads(SESSION_META_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    save_profile(
        "默认配置",
        from_path=SESSION_COOKIE_FILE,
        source=meta.get("browser", "legacy"),
        cookie_count=meta.get("cookie_count", 0),
    )
    set_active_profile_id(list_profiles()[0].profile_id)


def list_profiles() -> list[CookieProfile]:
    rows = _load_index()
    out: list[CookieProfile] = []
    for r in rows:
        pid = r.get("profile_id") or r.get("id")
        if not pid:
            continue
        p = CookieProfile(
            profile_id=str(pid),
            name=str(r.get("name", pid)),
            created_at=str(r.get("created_at", "")),
            source=str(r.get("source", "")),
            cookie_count=int(r.get("cookie_count", 0)),
        )
        if p.cookie_file.is_file():
            out.append(p)
    return out


def get_profile(profile_id: str) -> CookieProfile | None:
    for p in list_profiles():
        if p.profile_id == profile_id:
            return p
    return None


def get_active_profile_id() -> str | None:
    pid = _read_settings().get("active_profile_id")
    if pid and get_profile(str(pid)):
        return str(pid)
    profiles = list_profiles()
    return profiles[0].profile_id if profiles else None


def set_active_profile_id(profile_id: str | None) -> None:
    data = _read_settings()
    data["active_profile_id"] = profile_id
    _write_settings(data)


def save_profile(
    name: str,
    *,
    from_path: Path | None = None,
    source: str = "manual",
    cookie_count: int = 0,
) -> CookieProfile:
    _ensure_dirs()
    name = name.strip() or "未命名"
    src = from_path or SESSION_COOKIE_FILE
    if not src.is_file():
        raise FileNotFoundError("没有可保存的 Cookie 文件")

    profile_id = uuid.uuid4().hex[:8]
    dest_dir = PROFILES_DIR / profile_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_cookie = dest_dir / "cookies.txt"
    shutil.copy2(src, dest_cookie)

    if cookie_count <= 0 and dest_cookie.stat().st_size > 64:
        cookie_count = max(1, dest_cookie.read_text(encoding="utf-8", errors="replace").count("\n") - 5)

    created = datetime.now(timezone.utc).isoformat()
    meta = {
        "browser": source,
        "synced_at": created,
        "cookie_count": cookie_count,
    }
    (dest_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    row = {
        "profile_id": profile_id,
        "name": name,
        "created_at": created,
        "source": source,
        "cookie_count": cookie_count,
    }
    rows = _load_index()
    rows.append(row)
    _save_index(rows)

    set_active_profile_id(profile_id)
    shutil.copy2(dest_cookie, SESSION_COOKIE_FILE)
    SESSION_META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return CookieProfile(profile_id=profile_id, name=name, created_at=created, source=source, cookie_count=cookie_count)


_PROFILE_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")


def _valid_profile_id(profile_id: str) -> bool:
    return bool(_PROFILE_ID_RE.fullmatch(profile_id))


def delete_profile(profile_id: str) -> bool:
    if not _valid_profile_id(profile_id):
        return False
    rows = _load_index()
    new_rows = [r for r in rows if r.get("profile_id") != profile_id]
    if len(new_rows) == len(rows):
        return False
    _save_index(new_rows)
    dest = PROFILES_DIR / profile_id
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
    if get_active_profile_id() == profile_id:
        set_active_profile_id(new_rows[0]["profile_id"] if new_rows else None)
    return True


def profile_cookie_path(profile_id: str | None) -> Path | None:
    if not profile_id or not _valid_profile_id(str(profile_id)):
        return None
    p = get_profile(profile_id)
    if p and p.cookie_file.is_file():
        return p.cookie_file
    return None