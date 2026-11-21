from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QApplication,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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

_TEXT_DEFAULT = QColor("#f0f4fa")
_TEXT_STATUS = {
    TaskStatus.QUEUED: QColor("#d4dce8"),
    TaskStatus.MERGING: QColor("#ffd966"),
    TaskStatus.CANCELLED: QColor("#b0bccf"),
}


class ManagerBridge(QObject):
    task_updated = Signal(object)
    log_message = Signal(str)
    enqueue_started = Signal(str)
    enqueue_finished = Signal(str, object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Downloader")
        self.resize(960, 680)

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
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("YOUTUBE DOWNLOADER", objectName="titleLabel")
        sub = QLabel("Neural fetch · multi-thread · yt-dlp core", objectName="subtitleLabel")
        title_block.addWidget(title)
        title_block.addWidget(sub)
        header.addLayout(title_block)
        header.addStretch()
        layout.addLayout(header)

        url_card = QFrame(objectName="card")
        url_layout = QVBoxLayout(url_card)
        url_layout.addWidget(QLabel("视频 / 播放列表 URL"))
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
        opts = QGridLayout(opts_card)
        opts.setHorizontalSpacing(12)
        opts.setVerticalSpacing(8)

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

        self.chk_playlist = QCheckBox("展开播放列表（多线程并行）")
        self.chk_playlist.setChecked(True)

        opts.addWidget(QLabel("画质 / 格式"), 0, 0)
        opts.addWidget(self.format_combo, 0, 1)
        opts.addWidget(QLabel("登录态"), 0, 2)
        opts.addWidget(self.auth_combo, 0, 3)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Cookie 配置"))
        profile_row.addWidget(self.cookie_profile_combo, stretch=1)
        profile_row.addWidget(self.btn_save_profile)
        profile_row.addWidget(self.btn_delete_profile)
        opts.addLayout(profile_row, 1, 0, 1, 2)
        session_row = QHBoxLayout()
        session_row.addWidget(self.lbl_session, stretch=1)
        session_row.addWidget(self.btn_web_login)
        session_row.addWidget(self.btn_import_json)
        session_row.addWidget(self.btn_sync_cookie)
        opts.addLayout(session_row, 1, 2, 1, 2)
        opts.addWidget(QLabel("Cookie 文件"), 2, 0)
        cookie_row = QHBoxLayout()
        cookie_row.addWidget(self.cookie_path)
        cookie_row.addWidget(self.btn_browse_cookie)
        opts.addLayout(cookie_row, 2, 1, 1, 3)
        opts.addWidget(QLabel("保存位置"), 3, 0)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_input)
        dir_row.addWidget(self.btn_browse_dir)
        opts.addLayout(dir_row, 3, 1, 1, 2)
        opts.addWidget(QLabel("最大并发"), 3, 3)
        opts.addWidget(self.spin_workers, 4, 3)
        opts.addWidget(self.chk_playlist, 4, 0, 1, 2)
        layout.addWidget(opts_card)

        list_toolbar = QHBoxLayout()
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
        layout.addLayout(list_toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "标题", "状态", "进度", "速度", "操作"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        self.log_panel = QPlainTextEdit(objectName="logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(2000)
        self.log_panel.setPlaceholderText("系统日志…")
        layout.addWidget(self.log_panel, stretch=0)

        footer = QHBoxLayout()
        self.btn_open_dir = QPushButton("打开下载文件夹")
        self.btn_open_dir.clicked.connect(self._open_download_dir)
        footer.addWidget(self.btn_open_dir)
        footer.addStretch()
        layout.addLayout(footer)

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

        self._ensure_manager()

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
        self.cookie_path.setEnabled(use_file)
        self.btn_browse_cookie.setEnabled(use_file)
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

    @staticmethod
    def _paint_item(item: QTableWidgetItem, color: QColor | None = None) -> None:
        item.setForeground(color or _TEXT_DEFAULT)

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
        snap = (
            task.title,
            task.status,
            int(task.progress),
            task.speed,
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
                self._paint_item(id_item, QColor("#c8daf0"))
                self.table.setItem(row, 0, id_item)
                self.table.setItem(row, 1, QTableWidgetItem(""))
                self.table.setItem(row, 2, QTableWidgetItem(""))
                self.table.setItem(row, 4, QTableWidgetItem(""))
                bar = QProgressBar()
                bar.setRange(0, 100)
                self.table.setCellWidget(row, 3, bar)
                self.table.setCellWidget(row, 5, self._make_action_cell(task.task_id))
            finally:
                self.table.setUpdatesEnabled(True)

        title_item = self.table.item(row, 1)
        if title_item and task.title:
            title_item.setText(task.title[:80])

        status_item = self.table.item(row, 2)
        if status_item:
            status_item.setText(task.status.value)
            if task.status == TaskStatus.ERROR:
                status_item.setForeground(QColor("#ff8a8a"))
                status_item.setToolTip(task.error)
            elif task.status == TaskStatus.FINISHED:
                status_item.setForeground(QColor("#7dffb8"))
            elif task.status == TaskStatus.DOWNLOADING:
                status_item.setForeground(QColor("#7ae8ff"))
        else:
            status_item = QTableWidgetItem(task.status.value)
            self.table.setItem(row, 2, status_item)

        bar = self.table.cellWidget(row, 3)
        if isinstance(bar, QProgressBar):
            bar.setValue(int(task.progress))

        speed = task.speed or ("—" if task.status != TaskStatus.FINISHED else "完成")
        speed_item = self.table.item(row, 4)
        if speed_item:
            speed_item.setText(speed)

    def _make_action_cell(self, task_id: str) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)

        def _btn(text: str, handler) -> QPushButton:
            b = QPushButton(text)
            b.setFixedHeight(26)
            b.clicked.connect(handler)
            return b

        lay.addWidget(
            _btn("取消", lambda checked=False, tid=task_id: self._cancel_task(tid))
        )
        lay.addWidget(
            _btn("重试", lambda checked=False, tid=task_id: self._retry_task(tid))
        )
        lay.addWidget(
            _btn("打开", lambda checked=False, tid=task_id: self._open_task_file(tid))
        )
        lay.addWidget(
            _btn("复制", lambda checked=False, tid=task_id: self._copy_task_url(tid))
        )
        return wrap

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
            in (TaskStatus.FINISHED, TaskStatus.CANCELLED, TaskStatus.ERROR)
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

    def closeEvent(self, event) -> None:
        if self._manager:
            self._manager.shutdown(wait=False)
        super().closeEvent(event)