from __future__ import annotations

import http.cookiejar
import json
from datetime import datetime, timezone

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from yt_dlp.cookies import YoutubeDLCookieJar

from app.config import APP_DATA_DIR, SESSION_META_FILE
from app.core.cookie_sync import session_cookie_path, strip_ansi


def _normalize_domain(domain: str) -> str:
    domain = domain.strip()
    if domain and not domain.startswith(".") and domain.count(".") >= 1:
        return "." + domain
    return domain


def _qnetwork_to_cookie(qc: QNetworkCookie) -> http.cookiejar.Cookie | None:
    name = bytes(qc.name()).decode("utf-8", errors="replace")
    value = bytes(qc.value()).decode("utf-8", errors="replace")
    domain = _normalize_domain(qc.domain())
    if not name or not domain:
        return None
    path = qc.path() or "/"
    secure = qc.isSecure()
    if qc.expirationDate().isValid():
        expires = qc.expirationDate().toSecsSinceEpoch()
    else:
        expires = None
    rest: dict = {}
    if qc.isHttpOnly():
        rest["HttpOnly"] = None
    return http.cookiejar.Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=path,
        path_specified=bool(path),
        secure=secure,
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest=rest,
    )


_LOGIN_COOKIE_NAMES = frozenset(
    {
        "SID",
        "HSID",
        "SSID",
        "APISID",
        "SAPISID",
        "LOGIN_INFO",
        "__Secure-1PSID",
        "__Secure-3PSID",
        "__Secure-1PSIDTS",
        "__Secure-3PSIDTS",
    }
)


def has_youtube_login_cookies(cookies: list[QNetworkCookie]) -> bool:
    for qc in cookies:
        name = bytes(qc.name()).decode("utf-8", errors="replace")
        domain = qc.domain() or ""
        if "youtube.com" in domain and name in _LOGIN_COOKIE_NAMES:
            return True
    return False


def save_cookies_from_store(cookies: list[QNetworkCookie], browser_tag: str = "webview") -> int:
    out_path = session_cookie_path()
    jar = YoutubeDLCookieJar(str(out_path))
    kept = 0
    for qc in cookies:
        domain = qc.domain() or ""
        if "youtube.com" not in domain and "google.com" not in domain:
            continue
        c = _qnetwork_to_cookie(qc)
        if c:
            jar.set_cookie(c)
            kept += 1
    if kept == 0:
        for qc in cookies:
            c = _qnetwork_to_cookie(qc)
            if c:
                jar.set_cookie(c)
                kept += 1
    if kept == 0:
        return 0
    jar.save(ignore_discard=True, ignore_expires=True)

    SESSION_META_FILE.write_text(
        json.dumps(
            {
                "browser": browser_tag,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "cookie_count": kept,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return kept


class WebLoginDialog(QDialog):
    """登录 YouTube（支持扫码/账号），从内置浏览器导出 Cookie。"""

    def __init__(self, parent=None, target_video_url: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("登录 YouTube")
        self.resize(900, 640)
        self._saved_count = 0
        self._target_url = target_video_url

        layout = QVBoxLayout(self)
        hint = QLabel(
            "在下方完成 Google / YouTube 登录（可扫码）。\n"
            "年龄限制视频：登录后点「打开目标视频」或「打开 YouTube」，"
            "在页面中确认年满 18 岁后，再点「保存登录状态」。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        storage = APP_DATA_DIR / "webview_profile"
        storage.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile("YouTubeDownloaderLogin", self)
        profile.setPersistentStoragePath(str(storage))
        profile.setCachePath(str(storage / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        self._profile = profile
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(profile, self.view))
        layout.addWidget(self.view, stretch=1)

        row = QHBoxLayout()
        self.btn_home = QPushButton("打开 YouTube")
        self.btn_home.clicked.connect(
            lambda: self.view.load(QUrl("https://www.youtube.com/"))
        )
        self.btn_target = QPushButton("打开目标视频")
        self.btn_target.clicked.connect(self._load_target)
        if not target_video_url:
            self.btn_target.setEnabled(False)
        self.btn_save = QPushButton("保存登录状态")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._save_login)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_home)
        row.addWidget(self.btn_target)
        row.addStretch()
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        layout.addLayout(row)

        self.view.load(
            QUrl(
                "https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com/&passive=true"
            )
        )

    def _load_target(self) -> None:
        if self._target_url:
            self.view.load(QUrl(self._target_url))

    def _save_login(self) -> None:
        store = self._profile.cookieStore()

        def on_cookies(cookies: list[QNetworkCookie]) -> None:
            if not has_youtube_login_cookies(cookies):
                QMessageBox.warning(
                    self,
                    "未检测到有效登录",
                    "未找到 YouTube 登录 Cookie。\n"
                    "请先完成登录；年龄限制视频需打开该视频并确认 18 岁后再保存。",
                )
                return
            try:
                count = save_cookies_from_store(cookies, browser_tag="webview")
            except Exception as e:
                QMessageBox.warning(self, "保存失败", strip_ansi(str(e)))
                return
            if count < 1:
                QMessageBox.warning(self, "未检测到登录", "未找到可保存的 Cookie。")
                return
            self._saved_count = count
            QMessageBox.information(
                self,
                "已保存",
                f"已保存 {count} 条 Cookie。\n下载时请选择「本地已同步会话」。",
            )
            self.accept()

        store.getAllCookies(on_cookies)

    def saved_count(self) -> int:
        return self._saved_count