"""Dialog to load user's YouTube playlists and batch-download selections."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.core.auth import AuthConfig
from app.core.playlist_library import (
    PlaylistEntry,
    PlaylistLibraryError,
    PlaylistFetchResult,
    enrich_playlist_entry,
    fetch_user_playlists,
    parse_playlist_url,
)
from app.core.validators import normalize_youtube_url


class _FetchSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _EnrichSignals(QObject):
    done = Signal(str, object)


class _EnrichRunnable(QRunnable):
    def __init__(self, auth: AuthConfig, url: str, signals: _EnrichSignals) -> None:
        super().__init__()
        self._auth = auth
        self._url = url
        self._signals = signals

    def run(self) -> None:
        base = parse_playlist_url(self._url)
        if not base:
            return
        pl = enrich_playlist_entry(base, self._auth)
        self._signals.done.emit(self._url, pl)


class _FetchRunnable(QRunnable):
    def __init__(self, auth: AuthConfig, channel_hint: str | None, signals: _FetchSignals) -> None:
        super().__init__()
        self._auth = auth
        self._hint = channel_hint
        self._signals = signals

    def run(self) -> None:
        try:
            result = fetch_user_playlists(self._auth, channel_hint=self._hint)
            self._signals.done.emit(result)
        except PlaylistLibraryError as e:
            self._signals.failed.emit(str(e))
        except Exception as e:
            self._signals.failed.emit(str(e))


class MyPlaylistsDialog(QDialog):
    """Pick one or more playlists to expand and download."""

    playlists_chosen = Signal(list)

    def __init__(self, auth: AuthConfig, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("playlistDialog")
        self.setWindowTitle("我的播放列表")
        self.resize(560, 480)
        self._auth = auth
        self._pool = QThreadPool.globalInstance()
        self._pinned: dict[str, PlaylistEntry] = {}
        self._fetch_signals = _FetchSignals()
        self._fetch_signals.done.connect(self._on_fetched)
        self._fetch_signals.failed.connect(self._on_fetch_failed)
        self._enrich_signals = _EnrichSignals()
        self._enrich_signals.done.connect(self._on_enriched)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "需已登录 Cookie。列表含「稍后观看」「赞过」及账号下创建的播放列表。\n"
                "下方可粘贴播放列表链接（含 ?si= 亦可）；勾选后点「下载」或双击一行。\n"
                "若列表为空，可填 @频道名 或频道主页地址后点「刷新」。"
            )
        )

        hint_row = QHBoxLayout()
        hint_row.addWidget(QLabel("频道（可选）"))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("@你的频道 或留空")
        hint_row.addWidget(self.channel_input, stretch=1)
        layout.addLayout(hint_row)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("手动添加"))
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("https://www.youtube.com/playlist?list=PL…")
        self.btn_add_manual = QPushButton("加入列表")
        self.btn_add_manual.clicked.connect(self._add_manual_playlist)
        manual_row.addWidget(self.manual_input, stretch=1)
        manual_row.addWidget(self.btn_add_manual)
        layout.addLayout(manual_row)

        tool = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新列表")
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_select_none = QPushButton("全不选")
        self.btn_select_none.clicked.connect(self._select_none)
        tool.addWidget(self.btn_refresh)
        tool.addStretch()
        tool.addWidget(self.btn_select_all)
        tool.addWidget(self.btn_select_none)
        layout.addLayout(tool)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self._download_selected())
        layout.addWidget(self.list_widget, stretch=1)

        self.status = QLabel("点击「刷新列表」加载…")
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.btn_download = QPushButton("下载选中播放列表", objectName="primaryBtn")
        self.btn_download.clicked.connect(self._download_selected)
        self.btn_download.setEnabled(False)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(self.btn_download)
        actions.addWidget(btn_close)
        layout.addLayout(actions)

        if parent is not None and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())

        self._refresh()

    def _format_item_label(self, pl: PlaylistEntry) -> str:
        label = pl.title
        if pl.video_count is not None:
            label = f"{pl.title}  ({pl.video_count} 个视频)"
        return label

    def _append_playlist_item(self, pl: PlaylistEntry, *, select: bool = False) -> None:
        item = QListWidgetItem(self._format_item_label(pl))
        item.setData(Qt.ItemDataRole.UserRole, pl.url)
        item.setToolTip(pl.url)
        self.list_widget.addItem(item)
        if select:
            item.setSelected(True)
            self.list_widget.setCurrentItem(item)

    def _set_busy(self, busy: bool) -> None:
        self.btn_refresh.setEnabled(not busy)
        self.btn_download.setEnabled(not busy and self.list_widget.count() > 0)
        self.channel_input.setEnabled(not busy)

    @Slot()
    def _refresh(self) -> None:
        hint = self.channel_input.text().strip() or None
        self.status.setText("正在拉取播放列表…")
        self._set_busy(True)
        self.list_widget.clear()
        runnable = _FetchRunnable(self._auth, hint, self._fetch_signals)
        self._pool.start(runnable)

    @Slot(object)
    def _on_fetched(self, payload: object) -> None:
        assert isinstance(payload, PlaylistFetchResult)
        playlists = payload.entries
        self.list_widget.clear()
        known_urls = {pl.url for pl in playlists}
        for pl in playlists:
            assert isinstance(pl, PlaylistEntry)
            self._append_playlist_item(pl)
        for url, pl in self._pinned.items():
            if url not in known_urls:
                self._append_playlist_item(pl)
                known_urls.add(url)
        custom = max(0, len(playlists) - 2)
        hint = (
            f"共 {len(playlists)} 个列表（含稍后观看 / 赞过）"
            if custom
            else "仅「稍后观看」「赞过」可下；自建列表需有效登录 Cookie。"
        )
        extra = ""
        if payload.warnings:
            extra = " | " + payload.warnings[-1][:120]
        self.status.setText(f"{hint}{extra} — 多选后点下载。")
        self._set_busy(False)
        self.btn_download.setEnabled(len(playlists) > 0)

    @Slot(str)
    def _on_fetch_failed(self, msg: str) -> None:
        self._set_busy(False)
        self.status.setText("加载失败")
        QMessageBox.warning(self, "无法载入播放列表", msg)

    def _add_manual_playlist(self) -> None:
        raw = self.manual_input.text().strip()
        url = normalize_youtube_url(raw) or raw
        pl = parse_playlist_url(url)
        if not pl:
            QMessageBox.warning(
                self,
                "无法识别",
                "请粘贴播放列表链接（含 list=PL…）或 list=PL… 开头的 ID。",
            )
            return
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == pl.url:
                item.setSelected(True)
                self.list_widget.setCurrentItem(item)
                QMessageBox.information(
                    self,
                    "已存在",
                    "该播放列表已在列表中，已为你勾选。请点「下载选中播放列表」。",
                )
                return
        pending = PlaylistEntry(
            pl.playlist_id,
            f"{pl.playlist_id}（解析中…）",
            pl.url,
        )
        self._pinned[pl.url] = pending
        self._append_playlist_item(pending, select=True)
        self.manual_input.clear()
        self.btn_download.setEnabled(True)
        self.status.setText("已添加播放列表，正在解析视频数量…")
        self._pool.start(_EnrichRunnable(self._auth, pl.url, self._enrich_signals))

    @Slot(str, object)
    def _on_enriched(self, url: str, payload: object) -> None:
        if not isinstance(payload, PlaylistEntry):
            return
        self._pinned[url] = payload
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == url:
                item.setText(self._format_item_label(payload))
                item.setToolTip(payload.url)
                break
        vc = payload.video_count
        extra = f"{vc} 个视频" if vc is not None else "视频数量未知"
        self.status.setText(
            f"「{payload.title}」已就绪（{extra}）。请保持勾选后点「下载选中播放列表」。"
        )

    def _select_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setSelected(True)

    def _select_none(self) -> None:
        self.list_widget.clearSelection()

    def _download_selected(self) -> None:
        urls: list[str] = []
        for item in self.list_widget.selectedItems():
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                urls.append(str(url))
        if not urls:
            QMessageBox.information(self, "未选择", "请先选中一个或多个播放列表。")
            return
        self.playlists_chosen.emit(urls)
        self.accept()