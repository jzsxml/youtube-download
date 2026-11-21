from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMenu,
    QLabel,
    QLineEdit,
    QListView,
    QApplication,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.themes import STATUS_COLORS, ThemeId, apply_theme, get_saved_theme, save_theme

from app.config import DEFAULT_DOWNLOAD_DIR, DEFAULT_MAX_WORKERS, FORMAT_PRESETS
from app.core.auth import AuthConfig
from app.core.cookie_import import CookieImportError, import_json_cookies
from app.core.cookie_sync import (
    CookieSyncError,
    has_session_cookies,
    read_session_meta,
    sync_from_browser,
)
from app.core.cookie_profiles import (
    delete_profile,
    get_active_profile_id,
    list_profiles,
    migrate_legacy_session,
    save_profile,
    set_active_profile_id,
)
from app.core.errors import is_dpapi_error
from app.ui.login_dialog import WebLoginDialog
from app.core.download_manager import DownloadManager, DownloadTask, TaskStatus
from app.core.validators import normalize_youtube_url

class ManagerBridge(QObject):
    task_updated = Signal(object)
    log_message = Signal(str)
    enqueue_started = Signal(str)
    enqueue_finished = Signal(str, object)


class MainWindow(QMainWindow):
    def __init__(self, initial_theme: ThemeId | None = None, app_icon: QIcon | None = None) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Downloader")
        self._tray: QSystemTrayIcon | None = None
        self.resize(1000, 700)
        self._theme = initial_theme or get_saved_theme()

        self._bridge = ManagerBridge()
        self._bridge.task_updated.connect(self._on_task_updated)
        self._bridge.log_message.connect(self._append_log)
        self._bridge.enqueue_started.connect(self._on_enqueue_started)
        self._bridge.enqueue_finished.connect(self._on_enqueue_finished)
        self._submit_pending = 0

        self._task_rows: dict[str, int] = {}
        self._task_ui_state: dict[str, tuple] = {}
        self._manager: DownloadManager | None = None

        root = QWidget(objectName="centralRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("YOUTUBE DOWNLOADER", objectName="titleLabel")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("界面"))
        self.theme_combo = QComboBox(objectName="themeCombo")
        self.theme_combo.addItem("深色", ThemeId.DARK.value)
        self.theme_combo.addItem("白天", ThemeId.LIGHT.value)
        idx = self.theme_combo.findData(self._theme.value)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        header.addWidget(self.theme_combo)
        layout.addLayout(header)

        url_card = QFrame(objectName="card")
        url_layout = QVBoxLayout(url_card)
        url_layout.setContentsMargins(8, 6, 8, 6)
        url_layout.setSpacing(0)
        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.returnPressed.connect(self._start_download)
        url_row.addWidget(self.url_input, stretch=1)
        self.btn_download = QPushButton("开始下载", objectName="primaryBtn")
        self.btn_download.clicked.connect(self._start_download)
        url_row.addWidget(self.btn_download)
        url_layout.addLayout(url_row)
        layout.addWidget(url_card)

        opts_card = QFrame(objectName="card")
        opts_layout = QVBoxLayout(opts_card)
        opts_layout.setContentsMargins(8, 6, 8, 6)
        opts_layout.setSpacing(4)

        opts_columns = QHBoxLayout()
        opts_columns.setSpacing(12)

        settings_col = QVBoxLayout()
        settings_col.setSpacing(2)
        settings_col.addWidget(QLabel("下载设置", objectName="sectionTitle"))
        settings = QGridLayout()
        settings.setHorizontalSpacing(8)
        settings.setVerticalSpacing(4)

        self.format_combo = QComboBox()
        for key, (label, _) in FORMAT_PRESETS.items():
            self.format_combo.addItem(label, key)

        self.auth_combo = QComboBox()
        self.auth_combo.addItem("不登录（公开视频）", "none")
        self.auth_combo.addItem("已保存 Cookie 配置", "profile")
        self.auth_combo.addItem("当前会话（临时）", "session")
        self.auth_combo.addItem("Edge 实时读取（需关闭浏览器）", "edge")
        self.auth_combo.addItem("Chrome 实时读取（需关闭浏览器）", "chrome")
        self.auth_combo.addItem("cookies 文件", "cookiefile")
        self.auth_combo.currentIndexChanged.connect(self._on_auth_mode_changed)

        self.cookie_profile_combo = QComboBox()
        self.cookie_profile_combo.setMinimumWidth(180)
        self.cookie_profile_combo.currentIndexChanged.connect(self._on_profile_selected)

        for combo in (
            self.theme_combo,
            self.format_combo,
            self.auth_combo,
            self.cookie_profile_combo,
        ):
            self._apply_web_select_style(combo)

        self.btn_save_profile = QPushButton("保存为配置…")
        self.btn_save_profile.clicked.connect(self._save_cookie_profile)
        self.btn_delete_profile = QPushButton("删除配置")
        self.btn_delete_profile.clicked.connect(self._delete_cookie_profile)

        self.lbl_session = QLabel()
        self.btn_web_login = QPushButton("在应用内登录 YouTube")
        self.btn_web_login.setObjectName("primaryBtn")
        self.btn_web_login.clicked.connect(self._web_login)
        self.btn_sync_cookie = QPushButton("从浏览器导入（易失败）")
        self.btn_sync_cookie.setToolTip(
            "Windows 上常因 DPAPI 加密失败，请优先使用「在应用内登录」"
        )
        self.btn_sync_cookie.clicked.connect(self._sync_browser_login)
        self.btn_import_json = QPushButton("导入 JSON Cookie")
        self.btn_import_json.setToolTip(
            "将浏览器扩展导出的 JSON 转为本机会话（yt-dlp 使用 Netscape cookies.txt）"
        )
        self.btn_import_json.clicked.connect(self._import_json_cookies)

        self.cookie_path = QLineEdit()
        self.cookie_path.setPlaceholderText("cookies.txt / .json 路径")
        self.cookie_path.setEnabled(False)
        self.btn_browse_cookie = QPushButton("浏览…")
        self.btn_browse_cookie.setEnabled(False)
        self.btn_browse_cookie.clicked.connect(self._pick_cookie_file)

        self.dir_input = QLineEdit(str(DEFAULT_DOWNLOAD_DIR))
        self.btn_browse_dir = QPushButton("下载目录…")
        self.btn_browse_dir.clicked.connect(self._pick_output_dir)

        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 8)
        self.spin_workers.setValue(DEFAULT_MAX_WORKERS)

        self.chk_playlist = QCheckBox("展开播放列表", objectName="playlistChk")
        self.chk_playlist.setToolTip("仅对含 list= 或播放列表 URL 展开为多任务并行下载")
        self.chk_playlist.setChecked(True)
        self.chk_playlist.setCursor(Qt.CursorShape.PointingHandCursor)
        # 不自定义 ::indicator，与高级分组、浏览器网页同源系统绘制
        self.spin_workers.setMinimumWidth(80)

        settings.addWidget(QLabel("画质 / 格式"), 0, 0)
        settings.addWidget(self.format_combo, 0, 1, 1, 3)
        settings.addWidget(QLabel("保存位置"), 1, 0)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_input)
        dir_row.addWidget(self.btn_browse_dir)
        settings.addLayout(dir_row, 1, 1, 1, 3)
        settings.addWidget(QLabel("最大并发"), 2, 0)
        settings.addWidget(self.spin_workers, 2, 1)
        settings.addWidget(self.chk_playlist, 2, 2, 1, 2)
        settings_col.addLayout(settings)
        opts_columns.addLayout(settings_col, stretch=1)

        login_col = QVBoxLayout()
        login_col.setSpacing(2)
        login_col.addWidget(QLabel("登录与 Cookie", objectName="sectionTitle"))
        login = QGridLayout()
        login.setHorizontalSpacing(8)
        login.setVerticalSpacing(4)

        login.addWidget(QLabel("登录态"), 0, 0)
        login.addWidget(self.auth_combo, 0, 1, 1, 3)
        login.addWidget(QLabel("Cookie 配置"), 1, 0)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.cookie_profile_combo, stretch=1)
        profile_row.addWidget(self.btn_save_profile)
        profile_row.addWidget(self.btn_delete_profile)
        login.addLayout(profile_row, 1, 1, 1, 3)
        session_row = QHBoxLayout()
        session_row.addWidget(self.lbl_session, stretch=1)
        session_row.addWidget(self.btn_web_login)
        session_row.addWidget(self.btn_import_json)
        session_row.addWidget(self.btn_sync_cookie)
        login.addLayout(session_row, 2, 0, 1, 4)

        advanced = QGroupBox("高级：Cookie 文件 / 实时读浏览器", objectName="advancedLogin")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        adv_layout = QGridLayout(advanced)
        adv_layout.addWidget(QLabel("Cookie 文件"), 0, 0)
        cookie_row = QHBoxLayout()
        cookie_row.addWidget(self.cookie_path)
        cookie_row.addWidget(self.btn_browse_cookie)
        adv_layout.addLayout(cookie_row, 0, 1)
        login_col.addLayout(login)
        login_col.addWidget(advanced)
        opts_columns.addLayout(login_col, stretch=1)
        opts_layout.addLayout(opts_columns)
        advanced.toggled.connect(self._on_advanced_login_toggled)
        self._on_advanced_login_toggled(advanced.isChecked())

        layout.addWidget(opts_card)

        list_toolbar = QHBoxLayout()
        list_toolbar.setSpacing(6)
        self.btn_clear_done = QPushButton("清除已完成")
        self.btn_clear_done.clicked.connect(self._clear_finished_tasks)
        self.btn_clear_all = QPushButton("清空列表")
        self.btn_clear_all.clicked.connect(self._clear_all_tasks)
        self.btn_retry_failed = QPushButton("重试失败项")
        self.btn_retry_failed.clicked.connect(self._retry_failed_tasks)
        list_toolbar.addWidget(QLabel("下载列表"))
        list_toolbar.addStretch()
        list_toolbar.addWidget(self.btn_clear_done)
        list_toolbar.addWidget(self.btn_retry_failed)
        list_toolbar.addWidget(self.btn_clear_all)
        self.btn_open_dir = QPushButton("打开下载文件夹")
        self.btn_open_dir.clicked.connect(self._open_download_dir)
        list_toolbar.addWidget(self.btn_open_dir)
        layout.addLayout(list_toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "标题", "状态", "进度", "速度 / 剩余", "操作"]
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 76)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 268)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        self.log_panel = QPlainTextEdit(objectName="logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(2000)
        self.log_panel.setPlaceholderText("系统日志…")
        self.log_panel.setMinimumHeight(52)
        self.log_panel.setMaximumHeight(80)
        layout.addWidget(self.log_panel, stretch=0)

        migrate_legacy_session()
        self._refresh_profile_combo()
        self._refresh_session_label()
        if list_profiles():
            idx = self.auth_combo.findData("profile")
            if idx >= 0:
                self.auth_combo.setCurrentIndex(idx)
        elif has_session_cookies():
            idx = self.auth_combo.findData("session")
            if idx >= 0:
                self.auth_combo.setCurrentIndex(idx)
        else:
            idx = self.auth_combo.findData("none")
            if idx >= 0:
                self.auth_combo.setCurrentIndex(idx)

        if app_icon is not None and not app_icon.isNull():
            self.setWindowIcon(app_icon)
            self._setup_tray_icon(app_icon)

        self._ensure_manager()

    def _setup_tray_icon(self, icon: QIcon) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        open_main = menu.addAction("打开主窗口")
        open_main.triggered.connect(self._raise_main_window)
        open_dir = menu.addAction("打开下载文件夹")
        open_dir.triggered.connect(self._open_download_dir)
        menu.addSeparator()
        quit_app = menu.addAction("退出")
        quit_app.triggered.connect(self._quit_application)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("YouTube Downloader — 最小化后点击任务栏图标可恢复")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _raise_main_window(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        ):
            self._raise_main_window()

    def _quit_application(self) -> None:
        self.close()

    def _ensure_manager(self) -> None:
        output = Path(self.dir_input.text().strip() or DEFAULT_DOWNLOAD_DIR)
        output.mkdir(parents=True, exist_ok=True)
        if self._manager is None:
            self._manager = DownloadManager(
                output_dir=output,
                format_key=self.format_combo.currentData(),
                auth=self._current_auth(),
                max_workers=self.spin_workers.value(),
                on_task_update=lambda t: self._bridge.task_updated.emit(t),
                on_log=lambda m: self._bridge.log_message.emit(m),
                on_enqueue_started=lambda u: self._bridge.enqueue_started.emit(u),
                on_enqueue_finished=lambda u, ids: self._bridge.enqueue_finished.emit(
                    u, ids
                ),
            )
            return
        self._manager.output_dir = output
        self._manager.format_key = self.format_combo.currentData()
        self._manager.auth = self._current_auth()
        self._manager.on_enqueue_started = lambda u: self._bridge.enqueue_started.emit(u)
        self._manager.on_enqueue_finished = lambda u, ids: self._bridge.enqueue_finished.emit(
            u, ids
        )
        if self._manager.max_workers != self.spin_workers.value():
            self._append_log("提示: 并发数更改仅对本次启动后的新队列生效，重启应用可完全生效。")
            self._manager.max_workers = self.spin_workers.value()

    def _current_auth(self) -> AuthConfig:
        mode = self.auth_combo.currentData()
        path = self.cookie_path.text().strip() or None
        profile_id = self.cookie_profile_combo.currentData()
        return AuthConfig(mode=mode, cookie_path=path, profile_id=profile_id)

    def _refresh_profile_combo(self) -> None:
        block = self.cookie_profile_combo.blockSignals(True)
        self.cookie_profile_combo.clear()
        profiles = list_profiles()
        active = get_active_profile_id()
        for p in profiles:
            label = f"{p.name} ({p.cookie_count}条)"
            self.cookie_profile_combo.addItem(label, p.profile_id)
        if active:
            idx = self.cookie_profile_combo.findData(active)
            if idx >= 0:
                self.cookie_profile_combo.setCurrentIndex(idx)
        self.cookie_profile_combo.blockSignals(block)
        use_profile = self.auth_combo.currentData() == "profile"
        self.cookie_profile_combo.setEnabled(use_profile and bool(profiles))
        self.btn_save_profile.setEnabled(has_session_cookies() or bool(profiles))
        self.btn_delete_profile.setEnabled(bool(profiles) and use_profile)

    @Slot()
    def _on_profile_selected(self) -> None:
        pid = self.cookie_profile_combo.currentData()
        if pid:
            set_active_profile_id(str(pid))

    def _offer_save_profile_prompt(self, source: str) -> None:
        if not has_session_cookies():
            return
        name, ok = QInputDialog.getText(
            self,
            "保存 Cookie 配置",
            "为此登录态命名（可在下载时直接选择）：",
            text="我的 YouTube",
        )
        if not ok or not name.strip():
            return
        try:
            p = save_profile(name.strip(), source=source)
            self._refresh_profile_combo()
            idx = self.auth_combo.findData("profile")
            if idx >= 0:
                self.auth_combo.setCurrentIndex(idx)
            self._append_log(f"已保存 Cookie 配置「{p.name}」")
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))

    @Slot()
    def _save_cookie_profile(self) -> None:
        if not has_session_cookies():
            QMessageBox.warning(self, "无 Cookie", "请先登录、导入 JSON 或同步后再保存。")
            return
        self._offer_save_profile_prompt("manual")

    @Slot()
    def _delete_cookie_profile(self) -> None:
        pid = self.cookie_profile_combo.currentData()
        if not pid:
            return
        name = self.cookie_profile_combo.currentText()
        if (
            QMessageBox.question(
                self,
                "删除配置",
                f"确定删除「{name}」？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if delete_profile(str(pid)):
            self._refresh_profile_combo()
            self._append_log(f"已删除 Cookie 配置: {name}")

    def _refresh_session_label(self) -> None:
        if has_session_cookies():
            meta = read_session_meta()
            when = meta.get("synced_at", "未知")[:19].replace("T", " ")
            browser = meta.get("browser", "?")
            self.lbl_session.setText(
                f"已同步：{browser} · {when} UTC"
            )
        else:
            self.lbl_session.setText(
                "尚未登录 — 请点「在应用内登录 YouTube」（勿依赖从浏览器导入）"
            )

    @Slot()
    def _web_login(self) -> None:
        raw = self.url_input.text().strip()
        target = normalize_youtube_url(raw)
        dlg = WebLoginDialog(self, target_video_url=target)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.saved_count() > 0:
            self._refresh_session_label()
            self._offer_save_profile_prompt("webview")
            self._append_log(f"已通过内置浏览器保存 {dlg.saved_count()} 条 Cookie")

    @Slot()
    def _sync_browser_login(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        warn = QMessageBox.question(
            self,
            "从浏览器导入",
            "在 Windows 上，Chrome/Edge Cookie 常因 DPAPI 加密无法被第三方读取\n"
            "（尤其以管理员运行、或 Chrome 127+）。\n\n"
            "强烈建议使用「在应用内登录 YouTube」。\n\n"
            "仍要尝试从浏览器导入吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if warn != QMessageBox.StandardButton.Yes:
            return

        browser, ok = QInputDialog.getItem(
            self,
            "同步浏览器登录",
            "从哪个浏览器导出 Cookie？（请先在该浏览器登录 YouTube）",
            ["edge", "chrome"],
            0,
            False,
        )
        if not ok:
            return
        self._append_log(f"正在从 {browser} 同步 Cookie…")
        try:
            path = sync_from_browser(str(browser))
        except CookieSyncError as e:
            self._append_log(f"同步失败: {e}")
            if is_dpapi_error(str(e)):
                go = QMessageBox.question(
                    self,
                    "DPAPI 解密失败",
                    f"{e}\n\n是否现在打开「在应用内登录 YouTube」？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if go == QMessageBox.StandardButton.Yes:
                    self._web_login()
                return
            QMessageBox.warning(self, "同步失败", str(e))
            return
        self._append_log(f"已保存会话 Cookie: {path}")
        self._refresh_session_label()
        self._offer_save_profile_prompt(str(browser))
        QMessageBox.information(
            self,
            "同步成功",
            "登录态已保存到本机，下载时无需关闭浏览器。\n"
            "请将「登录态」保持为「本地已同步会话」。",
        )

    @Slot()
    def _on_auth_mode_changed(self) -> None:
        mode = self.auth_combo.currentData()
        use_file = mode == "cookiefile"
        if use_file:
            for w in self.findChildren(QGroupBox):
                if w.objectName() == "advancedLogin":
                    w.setChecked(True)
                    break
        self._on_advanced_login_toggled(
            use_file or any(
                g.isChecked()
                for g in self.findChildren(QGroupBox)
                if g.objectName() == "advancedLogin"
            )
        )
        if use_file:
            self.cookie_path.setEnabled(True)
            self.btn_browse_cookie.setEnabled(True)
        self._refresh_profile_combo()
        if mode in ("edge", "chrome") and not has_session_cookies():
            QMessageBox.information(
                self,
                "提示",
                "实时读取浏览器 Cookie 在本机常因 DPAPI 失败。\n"
                "请使用「在应用内登录」+「本地已同步会话」。",
            )

    @Slot()
    def _import_json_cookies(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择浏览器导出的 JSON Cookie",
            str(Path.home()),
            "JSON (*.json);;All (*.*)",
        )
        if not path:
            return
        try:
            out_path, count = import_json_cookies(Path(path), save_as_session=True)
        except CookieImportError as e:
            QMessageBox.warning(self, "导入失败", str(e))
            self._append_log(f"JSON Cookie 导入失败: {e}")
            return
        self._refresh_session_label()
        self._offer_save_profile_prompt(f"json:{Path(path).name}")
        self._append_log(f"已从 JSON 导入 {count} 条 Cookie → {out_path}")
        QMessageBox.information(
            self,
            "导入成功",
            f"已转换并保存 {count} 条 Cookie。\n"
            f"已切换为「本地已同步会话」。\n\n"
            "年龄限制视频：请先在浏览器里对该视频完成登录/年满确认后再重新导出 JSON。",
        )

    def _pick_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Cookie 文件",
            str(Path.home()),
            "Cookie (*.txt *.json);;Text (*.txt);;JSON (*.json);;All (*.*)",
        )
        if path:
            self.cookie_path.setText(path)
            if path.lower().endswith(".json"):
                idx = self.auth_combo.findData("cookiefile")
                if idx >= 0:
                    self.auth_combo.setCurrentIndex(idx)
                QMessageBox.information(
                    self,
                    "JSON 文件",
                    "已选择 JSON。下载时将自动转为同目录下的 .txt 给 yt-dlp 使用。\n"
                    "也可点「导入 JSON Cookie」直接写入本机会话（推荐）。",
                )

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "下载目录", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

    def _c(self, key: str) -> QColor:
        return QColor(STATUS_COLORS[self._theme].get(key, STATUS_COLORS[self._theme]["default"]))

    def _paint_item(self, item: QTableWidgetItem, color: QColor | None = None) -> None:
        item.setForeground(color or self._c("default"))

    def _apply_web_select_style(self, combo: QComboBox) -> None:
        list_view = QListView(combo)
        list_view.setSpacing(2)
        combo.setView(list_view)

    @Slot()
    def _on_theme_changed(self) -> None:
        raw = self.theme_combo.currentData()
        try:
            theme = ThemeId(raw)
        except ValueError:
            theme = ThemeId.DARK
        self._theme = theme
        save_theme(theme)
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)
        for tid in list(self._task_rows.keys()):
            self._task_ui_state.pop(tid, None)
        if self._manager:
            for task in self._manager.iter_tasks():
                self._on_task_updated(copy.copy(task))

    def _on_advanced_login_toggled(self, checked: bool) -> None:
        self.cookie_path.setEnabled(checked)
        self.btn_browse_cookie.setEnabled(checked)

    @staticmethod
    def _format_speed_cell(task: DownloadTask) -> str:
        if task.status == TaskStatus.FINISHED:
            return "完成"
        if task.status == TaskStatus.MERGING:
            return "合并中…"
        if task.status == TaskStatus.QUEUED:
            return "等待"
        if task.status == TaskStatus.ERROR:
            return "—"
        if task.status == TaskStatus.CANCELLED:
            return "已取消"
        if task.status == TaskStatus.PAUSED:
            return "已暂停"
        parts: list[str] = []
        if task.speed:
            parts.append(task.speed)
        if task.eta:
            parts.append(f"剩 {task.eta}")
        return " · ".join(parts) if parts else "连接中…"

    def _open_download_dir(self) -> None:
        path = self.dir_input.text().strip() or str(DEFAULT_DOWNLOAD_DIR)
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    @Slot()
    def _start_download(self) -> None:
        raw = self.url_input.text().strip()
        url = normalize_youtube_url(raw)
        if not url:
            QMessageBox.warning(self, "URL 无效", "请输入有效的 YouTube 链接或 11 位视频 ID。")
            return
        mode = self.auth_combo.currentData()
        if mode == "profile" and not list_profiles():
            QMessageBox.warning(
                self,
                "无 Cookie 配置",
                "请先保存 Cookie 配置，或改选「不登录」。",
            )
            return
        if mode == "session" and not has_session_cookies():
            QMessageBox.warning(
                self,
                "尚未同步登录",
                "请先登录/导入，或改选「已保存 Cookie 配置」。",
            )
            return
        if mode in ("edge", "chrome"):
            self._append_log(
                f"提示: 实时读取 {mode} 需关闭浏览器；推荐「本地已同步会话」。"
            )
        self._ensure_manager()
        assert self._manager is not None
        self._append_log(f"提交: {url}")
        self._manager.enqueue_async(
            url, expand_playlist=self.chk_playlist.isChecked()
        )
        self.url_input.clear()

    @Slot(str)
    def _on_enqueue_started(self, _url: str) -> None:
        self._submit_pending += 1
        if self._submit_pending == 1:
            self.btn_download.setText("解析中…")

    @Slot(str, object)
    def _on_enqueue_finished(self, _url: str, _ids: object) -> None:
        self._submit_pending = max(0, self._submit_pending - 1)
        if self._submit_pending == 0:
            self.btn_download.setText("开始下载")

    @Slot(object)
    def _on_task_updated(self, task: DownloadTask) -> None:
        prev_snap = self._task_ui_state.get(task.task_id)
        prev_status = prev_snap[1] if prev_snap else None
        speed_text = self._format_speed_cell(task)
        snap = (
            task.title,
            task.status,
            int(task.progress),
            speed_text,
            task.error,
        )
        if self._task_ui_state.get(task.task_id) == snap:
            return
        self._task_ui_state[task.task_id] = snap

        row = self._task_rows.get(task.task_id)
        if row is None:
            self.table.setUpdatesEnabled(False)
            try:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._task_rows[task.task_id] = row
                id_item = QTableWidgetItem(task.task_id)
                self._paint_item(id_item, self._c("id"))
                self.table.setItem(row, 0, id_item)
                self.table.setItem(row, 1, QTableWidgetItem(""))
                self.table.setItem(row, 2, QTableWidgetItem(""))
                self.table.setItem(row, 4, QTableWidgetItem(""))
                bar = QProgressBar()
                bar.setRange(0, 100)
                self.table.setCellWidget(row, 3, bar)
                self.table.setCellWidget(row, 5, self._make_action_cell(task))
            finally:
                self.table.setUpdatesEnabled(True)

        title_item = self.table.item(row, 1)
        if title_item and task.title:
            title_item.setText(task.title[:80])

        status_item = self.table.item(row, 2)
        if status_item:
            status_item.setText(task.status.value)
            if task.status == TaskStatus.ERROR:
                status_item.setForeground(self._c("error"))
                status_item.setToolTip(task.error)
            elif task.status == TaskStatus.FINISHED:
                status_item.setForeground(self._c("finished"))
            elif task.status == TaskStatus.DOWNLOADING:
                status_item.setForeground(self._c("downloading"))
            elif task.status == TaskStatus.MERGING:
                status_item.setForeground(self._c("merging"))
            elif task.status == TaskStatus.CANCELLED:
                status_item.setForeground(self._c("cancelled"))
            elif task.status == TaskStatus.PAUSED:
                status_item.setForeground(self._c("paused"))
            else:
                status_item.setForeground(self._c("queued"))
        else:
            status_item = QTableWidgetItem(task.status.value)
            self.table.setItem(row, 2, status_item)

        bar = self.table.cellWidget(row, 3)
        if isinstance(bar, QProgressBar):
            bar.setValue(int(task.progress))

        speed_item = self.table.item(row, 4)
        if speed_item:
            speed_item.setText(speed_text)
            self._paint_item(speed_item, self._c("speed"))
        else:
            si = QTableWidgetItem(speed_text)
            self._paint_item(si, self._c("speed"))
            self.table.setItem(row, 4, si)

        if prev_status != task.status:
            self.table.setCellWidget(row, 5, self._make_action_cell(task))

    def _make_action_cell(self, task: DownloadTask) -> QWidget:
        task_id = task.task_id
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)

        def _btn(text: str, tip: str, handler) -> QPushButton:
            b = QPushButton(text, objectName="tableActBtn")
            b.setToolTip(tip)
            b.setFixedHeight(28)
            b.setMinimumWidth(40)
            b.clicked.connect(handler)
            return b

        active = task.status in (
            TaskStatus.QUEUED,
            TaskStatus.DOWNLOADING,
            TaskStatus.MERGING,
        )
        if active:
            lay.addWidget(
                _btn("暂停", "暂停下载（保留进度，可继续）", lambda _=False, tid=task_id: self._pause_task(tid))
            )
        if task.status == TaskStatus.PAUSED:
            lay.addWidget(
                _btn(
                    "继续",
                    "从 .part 断点续传",
                    lambda _=False, tid=task_id: self._resume_task(tid),
                )
            )
        if task.status in (TaskStatus.ERROR, TaskStatus.CANCELLED):
            lay.addWidget(
                _btn(
                    "重试",
                    "重新下载（中断任务将从 .part 断点续传）",
                    lambda _=False, tid=task_id: self._retry_task(tid),
                )
            )
        if active or task.status == TaskStatus.PAUSED:
            lay.addWidget(
                _btn("取消", "停止并标记为已取消", lambda _=False, tid=task_id: self._cancel_task(tid))
            )
        lay.addWidget(
            _btn("打开", "打开文件或下载文件夹", lambda _=False, tid=task_id: self._open_task_file(tid))
        )
        lay.addWidget(
            _btn("复制", "复制视频链接", lambda _=False, tid=task_id: self._copy_task_url(tid))
        )
        lay.addStretch()
        return wrap

    def _pause_task(self, task_id: str) -> None:
        if not self._manager:
            return
        if self._manager.pause_task(task_id):
            self._append_log(f"暂停任务 {task_id}")
        else:
            QMessageBox.information(self, "无法暂停", "任务不存在或当前状态不可暂停。")

    def _resume_task(self, task_id: str) -> None:
        if not self._manager:
            return
        if self._manager.resume_task(task_id):
            self._append_log(f"继续任务 {task_id}")
        else:
            QMessageBox.information(self, "无法继续", "任务不存在或仍在下载中。")

    def _cancel_task(self, task_id: str) -> None:
        if self._manager:
            self._manager.cancel_task(task_id)

    def _retry_task(self, task_id: str) -> None:
        if not self._manager:
            return
        if self._manager.retry_task(task_id):
            self._append_log(f"重试任务 {task_id}")
        else:
            QMessageBox.information(self, "无法重试", "任务不存在或仍在下载中。")

    def _open_task_file(self, task_id: str) -> None:
        if not self._manager:
            return
        task = self._manager.get_task(task_id)
        if not task:
            return
        if task.output_path and Path(task.output_path).is_file():
            os.startfile(task.output_path)
            return
        self._open_download_dir()

    def _copy_task_url(self, task_id: str) -> None:
        if not self._manager:
            return
        task = self._manager.get_task(task_id)
        if task:
            QApplication.clipboard().setText(task.url)
            self._append_log(f"已复制链接: {task.url[:60]}…")

    def _clear_finished_tasks(self) -> None:
        if not self._manager:
            return
        ids = self._manager.remove_tasks_where(
            lambda t: t.status
            in (TaskStatus.FINISHED, TaskStatus.CANCELLED, TaskStatus.ERROR, TaskStatus.PAUSED)
        )
        self._purge_table_rows(ids)

    def _clear_all_tasks(self) -> None:
        if not self._manager:
            return
        if (
            QMessageBox.question(
                self,
                "清空列表",
                "仅清除列表记录，不会删除已下载文件。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        ids = self._manager.remove_tasks_where(lambda t: True)
        self._purge_table_rows(ids)

    def _retry_failed_tasks(self) -> None:
        if not self._manager:
            return
        n = 0
        for task in list(self._manager.iter_tasks()):
            if task.status == TaskStatus.ERROR:
                if self._manager.retry_task(task.task_id):
                    n += 1
        self._append_log(f"已提交 {n} 个失败任务重试")

    def _purge_table_rows(self, task_ids: list[str]) -> None:
        for tid in task_ids:
            self._task_ui_state.pop(tid, None)
            self._task_rows.pop(tid, None)
        self.table.setRowCount(0)
        self._task_rows.clear()
        if self._manager:
            for task in self._manager.iter_tasks():
                self._task_ui_state.pop(task.task_id, None)
                self._on_task_updated(copy.copy(task))

    @Slot(str)
    def _append_log(self, text: str) -> None:
        self.log_panel.appendPlainText(text)

    def _has_background_work(self) -> bool:
        if self._submit_pending > 0:
            return True
        return bool(self._manager and self._manager.has_active_downloads())

    def _ask_before_close(self) -> str:
        """
        Returns 'exit', 'minimize', or 'cancel'.
        """
        if not self._has_background_work():
            return "exit"
        downloading = merging = queued = 0
        if self._manager:
            downloading, merging, queued = self._manager.count_active_tasks()
        extra = ""
        if self._submit_pending > 0:
            extra = f"\n另有 {self._submit_pending} 个链接正在解析入队。"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("仍有下载任务")
        msg.setText(
            f"正在下载 {downloading} 个、合并中 {merging} 个、排队 {queued} 个。"
            f"{extra}"
        )
        msg.setInformativeText(
            "选择「最小化继续下载」将在后台继续；选择「退出」会停止任务，"
            "但未下完的文件会留在下载目录（.part），下次下载同一视频可自动续传。"
        )
        btn_min = msg.addButton("最小化继续下载", QMessageBox.ButtonRole.YesRole)
        btn_exit = msg.addButton("退出", QMessageBox.ButtonRole.NoRole)
        btn_stay = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_min)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_min:
            return "minimize"
        if clicked == btn_exit:
            return "exit"
        if clicked == btn_stay:
            return "cancel"
        return "cancel"

    def _finalize_shutdown(self) -> None:
        if self._manager:
            self._manager.shutdown(wait=False)
        if self._tray:
            self._tray.hide()

    def closeEvent(self, event) -> None:
        choice = self._ask_before_close()
        if choice == "cancel":
            event.ignore()
            return
        if choice == "minimize":
            event.ignore()
            self.showMinimized()
            if self._tray is not None:
                self._tray.showMessage(
                    "YouTube Downloader",
                    "下载仍在进行，点击托盘图标可打开主窗口",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
            return
        self._finalize_shutdown()
        event.accept()
        super().closeEvent(event)