"""Browse a channel's videos / Shorts with pagination and batch download."""

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.auth import AuthConfig
from app.core.channel_catalog import (
    PAGE_SIZE,
    ChannelCatalogError,
    ChannelPageResult,
    ChannelTab,
    ChannelVideoEntry,
    fetch_channel_page,
    filter_entries_by_title,
    format_entry_label,
    normalize_channel_base,
)


class _FetchSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _FetchRunnable(QRunnable):
    def __init__(
        self,
        auth: AuthConfig,
        channel_text: str,
        tab: ChannelTab,
        page: int,
        signals: _FetchSignals,
    ) -> None:
        super().__init__()
        self._auth = auth
        self._channel = channel_text
        self._tab = tab
        self._page = page
        self._signals = signals

    def run(self) -> None:
        try:
            result = fetch_channel_page(
                self._auth, self._channel, self._tab, self._page
            )
            self._signals.done.emit(result)
        except ChannelCatalogError as e:
            self._signals.failed.emit(str(e))
        except Exception as e:
            self._signals.failed.emit(str(e))


class ChannelVideosDialog(QDialog):
    videos_chosen = Signal(list)

    def __init__(self, auth: AuthConfig, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("playlistDialog")
        self.setWindowTitle("频道视频")
        self.resize(620, 520)
        self._auth = auth
        self._pool = QThreadPool.globalInstance()
        self._fetch_signals = _FetchSignals()
        self._fetch_signals.done.connect(self._on_fetched)
        self._fetch_signals.failed.connect(self._on_fetch_failed)
        self._channel_text = ""
        self._page_by_tab: dict[ChannelTab, int] = {
            ChannelTab.VIDEOS: 1,
            ChannelTab.SHORTS: 1,
        }
        self._has_next_by_tab: dict[ChannelTab, bool] = {
            ChannelTab.VIDEOS: False,
            ChannelTab.SHORTS: False,
        }
        self._raw_entries: list[ChannelVideoEntry] = []
        self._checked_by_tab: dict[ChannelTab, set[str]] = {
            ChannelTab.VIDEOS: set(),
            ChannelTab.SHORTS: set(),
        }
        self._populating_list = False

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "粘贴频道 @ 或主页链接。视频与 Shorts 分 Tab 显示，每页最多 "
                f"{PAGE_SIZE} 条；勾选可多选，翻页后仍保留；搜索仅过滤当前页。"
            )
        )

        row = QHBoxLayout()
        row.addWidget(QLabel("频道"))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText(
            "https://www.youtube.com/@名称 或 @名称"
        )
        self.btn_load = QPushButton("加载")
        self.btn_load.clicked.connect(self._load_channel)
        row.addWidget(self.channel_input, stretch=1)
        row.addWidget(self.btn_load)
        layout.addLayout(row)

        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "视频")
        self.tabs.addTab(QWidget(), "Shorts")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索标题"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("当前页关键字过滤…")
        self.search_input.textChanged.connect(self._apply_search_filter)
        search_row.addWidget(self.search_input, stretch=1)
        layout.addLayout(search_row)

        page_row = QHBoxLayout()
        self.btn_prev = QPushButton("上一页")
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next = QPushButton("下一页")
        self.btn_next.clicked.connect(self._next_page)
        self.lbl_page = QLabel("第 1 页")
        page_row.addWidget(self.btn_prev)
        page_row.addWidget(self.lbl_page)
        page_row.addWidget(self.btn_next)
        page_row.addStretch()
        layout.addLayout(page_row)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.itemChanged.connect(self._on_item_check_changed)
        layout.addWidget(self.list_widget, stretch=1)

        self.status = QLabel("输入频道后点「加载」。")
        layout.addWidget(self.status)

        tool = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(self._select_all_visible)
        self.btn_select_none = QPushButton("全不选本页")
        self.btn_select_none.clicked.connect(self._select_none)
        self.btn_clear_picked = QPushButton("清空已选")
        self.btn_clear_picked.setToolTip("清除当前 Tab 内所有已勾选（含其他页）")
        self.btn_clear_picked.clicked.connect(self._clear_picked)
        tool.addWidget(self.btn_select_all)
        tool.addWidget(self.btn_select_none)
        tool.addWidget(self.btn_clear_picked)
        tool.addStretch()
        self.lbl_picked = QLabel("已选 0")
        tool.addWidget(self.lbl_picked)
        self.btn_download = QPushButton("下载选中", objectName="primaryBtn")
        self.btn_download.clicked.connect(self._download_selected)
        self.btn_download.setEnabled(False)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)
        tool.addWidget(self.btn_download)
        tool.addWidget(btn_close)
        layout.addLayout(tool)

        if parent is not None and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())
        self._update_page_buttons()

    def _current_tab(self) -> ChannelTab:
        return ChannelTab.SHORTS if self.tabs.currentIndex() == 1 else ChannelTab.VIDEOS

    def _set_busy(self, busy: bool) -> None:
        self.btn_load.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self.channel_input.setEnabled(not busy)
        if busy:
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
        else:
            self._update_page_buttons()

    @Slot()
    def _load_channel(self) -> None:
        text = self.channel_input.text().strip()
        base = normalize_channel_base(text)
        if not base:
            QMessageBox.warning(
                self,
                "频道无效",
                "请粘贴有效的 YouTube 频道链接或 @名称。",
            )
            return
        self._channel_text = text
        self._page_by_tab[ChannelTab.VIDEOS] = 1
        self._page_by_tab[ChannelTab.SHORTS] = 1
        self._checked_by_tab[ChannelTab.VIDEOS].clear()
        self._checked_by_tab[ChannelTab.SHORTS].clear()
        self._update_picked_label()
        self.search_input.clear()
        self._fetch_page(self._current_tab(), 1)

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        if not self._channel_text:
            return
        tab = ChannelTab.SHORTS if index == 1 else ChannelTab.VIDEOS
        self.search_input.clear()
        self._update_picked_label()
        self._fetch_page(tab, self._page_by_tab[tab])

    def _fetch_page(self, tab: ChannelTab, page: int) -> None:
        if not self._channel_text:
            return
        self._page_by_tab[tab] = page
        tab_label = "Shorts" if tab == ChannelTab.SHORTS else "视频"
        self.status.setText(f"正在加载{tab_label} 第 {page} 页…")
        self._set_busy(True)
        self.list_widget.clear()
        runnable = _FetchRunnable(
            self._auth, self._channel_text, tab, page, self._fetch_signals
        )
        self._pool.start(runnable)

    @Slot()
    def _prev_page(self) -> None:
        tab = self._current_tab()
        page = self._page_by_tab[tab]
        if page <= 1:
            return
        self.search_input.clear()
        self._fetch_page(tab, page - 1)

    @Slot()
    def _next_page(self) -> None:
        tab = self._current_tab()
        if not self._has_next_by_tab[tab]:
            return
        self.search_input.clear()
        self._fetch_page(tab, self._page_by_tab[tab] + 1)

    @Slot(object)
    def _on_fetched(self, payload: object) -> None:
        assert isinstance(payload, ChannelPageResult)
        tab = payload.tab
        self._has_next_by_tab[tab] = payload.has_next
        self._raw_entries = list(payload.entries)
        if self._current_tab() == tab:
            self._populate_list(self._raw_entries)
            shown = len(self._raw_entries)
            extra = "（满页，可下一页）" if payload.has_next else ""
            self.status.setText(
                f"{tab.value} 第 {payload.page} 页：{shown} 条{extra} — 勾选后可跨页累积下载。"
            )
            self.lbl_page.setText(f"第 {payload.page} 页")
        self._set_busy(False)
        self.btn_download.setEnabled(bool(self._raw_entries))
        self._update_page_buttons()

    @Slot(str)
    def _on_fetch_failed(self, msg: str) -> None:
        self._set_busy(False)
        self._raw_entries = []
        self.list_widget.clear()
        self.status.setText("加载失败")
        QMessageBox.warning(self, "无法载入频道", msg)
        self._update_page_buttons()

    def _picked_set(self) -> set[str]:
        return self._checked_by_tab[self._current_tab()]

    def _update_picked_label(self) -> None:
        n = len(self._picked_set())
        self.lbl_picked.setText(f"已选 {n}")
        self.btn_download.setEnabled(n > 0)
        self.btn_clear_picked.setEnabled(n > 0)

    def _populate_list(self, entries: list[ChannelVideoEntry]) -> None:
        picked = self._picked_set()
        self._populating_list = True
        block = self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for ent in entries:
            item = QListWidgetItem(format_entry_label(ent))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, ent.url)
            item.setToolTip(ent.url)
            if ent.url in picked:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(block)
        self._populating_list = False
        self._update_picked_label()

    @Slot(QListWidgetItem)
    def _on_item_check_changed(self, item: QListWidgetItem) -> None:
        if self._populating_list:
            return
        url = item.data(Qt.ItemDataRole.UserRole)
        if not url:
            return
        url = str(url)
        picked = self._picked_set()
        if item.checkState() == Qt.CheckState.Checked:
            picked.add(url)
        else:
            picked.discard(url)
        self._update_picked_label()

    @Slot()
    def _apply_search_filter(self) -> None:
        if not self._raw_entries:
            return
        filtered = filter_entries_by_title(
            self._raw_entries, self.search_input.text()
        )
        self._populate_list(filtered)
        kw = self.search_input.text().strip()
        if kw:
            self.status.setText(
                f"当前页搜索「{kw}」：{len(filtered)} / {len(self._raw_entries)} 条"
            )

    def _update_page_buttons(self) -> None:
        tab = self._current_tab()
        page = self._page_by_tab[tab]
        self.lbl_page.setText(f"第 {page} 页")
        ready = bool(self._channel_text)
        self.btn_prev.setEnabled(ready and page > 1)
        self.btn_next.setEnabled(ready and self._has_next_by_tab[tab])

    def _select_all_visible(self) -> None:
        picked = self._picked_set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item:
                continue
            item.setCheckState(Qt.CheckState.Checked)
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                picked.add(str(url))
        self._update_picked_label()

    def _select_none(self) -> None:
        picked = self._picked_set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item:
                continue
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                picked.discard(str(url))
            item.setCheckState(Qt.CheckState.Unchecked)
        self.list_widget.clearSelection()
        self._update_picked_label()

    def _clear_picked(self) -> None:
        self._picked_set().clear()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_picked_label()

    def _download_selected(self) -> None:
        urls = sorted(self._picked_set())
        if not urls:
            QMessageBox.information(
                self,
                "未选择",
                "请勾选要下载的视频（可跨页勾选，当前 Tab 内有效）。",
            )
            return
        tab_name = "Shorts" if self._current_tab() == ChannelTab.SHORTS else "视频"
        self.videos_chosen.emit(urls)
        self._picked_set().clear()
        self._update_picked_label()
        self._append_status_after_download(tab_name, len(urls))

    def _append_status_after_download(self, tab_name: str, count: int) -> None:
        self.status.setText(f"已提交 {count} 个{tab_name} 下载任务，可继续勾选或关闭窗口。")
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self.accept()