from __future__ import annotations

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import yt_dlp

from app.core.auth import AuthConfig
from app.core.cookie_sync import strip_ansi
from app.config import FORMAT_FALLBACK, PROGRESS_UI_INTERVAL
from app.core.ui_bridge import ProgressThrottler
from app.core.downloader import build_ydl_opts, build_ydl_opts_with_format, extract_urls_from_playlist
from app.core.validators import should_expand_playlist
from app.core.errors import (
    brief_video_unavailable_message,
    format_youtube_auth_hint,
    is_cookie_infrastructure_error,
    is_format_unavailable,
    is_login_required_message,
    is_video_unavailable_error,
)


class TaskStatus(str, Enum):
    QUEUED = "排队"
    DOWNLOADING = "下载中"
    MERGING = "合并中"
    PAUSED = "已暂停"
    FINISHED = "完成"
    ERROR = "失败"
    CANCELLED = "已取消"


@dataclass
class DownloadTask:
    task_id: str
    url: str
    status: TaskStatus = TaskStatus.QUEUED
    title: str = ""
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    error: str = ""
    output_path: str = ""


TaskEventCallback = Callable[[DownloadTask], None]
LogCallback = Callable[[str], None]


@dataclass
class DownloadManager:
    output_dir: Path
    format_key: str
    auth: AuthConfig
    max_workers: int = 3
    on_task_update: TaskEventCallback | None = None
    on_log: LogCallback | None = None
    _tasks: dict[str, DownloadTask] = field(default_factory=dict)
    _cancel: dict[str, threading.Event] = field(default_factory=dict)
    _pause_pending: set[str] = field(default_factory=set, repr=False)
    _executor: ThreadPoolExecutor | None = field(default=None, repr=False)
    _futures: list[Future] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _submit_executor: ThreadPoolExecutor | None = field(default=None, repr=False)
    on_enqueue_started: Callable[[str], None] | None = None
    on_enqueue_finished: Callable[[str, list[str]], None] | None = None
    _progress_throttle: ProgressThrottler = field(
        default_factory=lambda: ProgressThrottler(PROGRESS_UI_INTERVAL), repr=False
    )

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(strip_ansi(msg))

    def _emit(self, task: DownloadTask, *, force: bool = False) -> None:
        if not self._progress_throttle.allow(task.task_id, force=force):
            return
        if self.on_task_update:
            self.on_task_update(copy.copy(task))

    def _set_status(self, task: DownloadTask, status: TaskStatus) -> None:
        task.status = status
        self._emit(task, force=True)

    def _on_download_stopped(self, task_id: str, task: DownloadTask) -> None:
        with self._lock:
            paused = task_id in self._pause_pending
            if paused:
                self._pause_pending.discard(task_id)
        ev = self._cancel.get(task_id)
        if paused:
            if ev:
                ev.clear()
            task.speed = ""
            task.eta = ""
            self._set_status(task, TaskStatus.PAUSED)
            self._log(f"[{task_id}] 已暂停（点「继续」将断点续传）")
        else:
            self._set_status(task, TaskStatus.CANCELLED)
            self._log(
                f"[{task_id}] 已取消（未下完部分已保留，点「重试」或再次提交同链接可断点续传）"
            )

    def _resolve_urls(self, url: str, expand_playlist: bool) -> list[str]:
        if not should_expand_playlist(url, expand_playlist):
            return [url]
        try:
            urls = extract_urls_from_playlist(url, self.auth)
            self._log(f"展开为 {len(urls)} 个任务")
            return urls
        except Exception as e:
            err = strip_ansi(str(e))
            if is_login_required_message(err) and not self.auth.cookies_will_be_sent():
                self._log(
                    "播放列表解析需要登录：请先在应用内登录并选择「本地已同步会话」"
                )
            else:
                self._log(f"播放列表解析失败，按单条下载: {err}")
            return [url]

    def _enqueue_urls(self, urls: list[str]) -> list[str]:
        ids: list[str] = []
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

        for u in urls:
            task_id = uuid.uuid4().hex[:8]
            task = DownloadTask(task_id=task_id, url=u)
            cancel = threading.Event()
            with self._lock:
                self._tasks[task_id] = task
                self._cancel[task_id] = cancel
            self._emit(task, force=True)
            future = self._executor.submit(self._run_one, task_id)
            with self._lock:
                self._futures.append(future)
            ids.append(task_id)
        self._prune_futures()
        return ids

    def _prune_futures(self) -> None:
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]

    def enqueue(self, url: str, expand_playlist: bool = True) -> list[str]:
        """Blocking enqueue (avoid calling from UI thread)."""
        urls = self._resolve_urls(url, expand_playlist)
        return self._enqueue_urls(urls)

    def enqueue_async(self, url: str, expand_playlist: bool = True) -> None:
        """Parse playlist and enqueue on a background thread (UI-safe)."""
        if self.on_enqueue_started:
            self.on_enqueue_started(url)
        with self._lock:
            if self._submit_executor is None:
                self._submit_executor = ThreadPoolExecutor(max_workers=1)

        def work() -> None:
            try:
                urls = self._resolve_urls(url, expand_playlist)
                ids = self._enqueue_urls(urls)
                if self.on_enqueue_finished:
                    self.on_enqueue_finished(url, ids)
            except Exception as e:
                self._log(f"提交失败: {strip_ansi(str(e))}")
                if self.on_enqueue_finished:
                    self.on_enqueue_finished(url, [])

        self._submit_executor.submit(work)

    def enqueue_many_async(self, urls: list[str], expand_playlist: bool = True) -> None:
        """Parse and enqueue multiple playlist URLs on a background thread."""
        urls = [u.strip() for u in urls if u and u.strip()]
        if not urls:
            return
        label = f"批量播放列表 ({len(urls)} 个)"
        if self.on_enqueue_started:
            self.on_enqueue_started(label)
        with self._lock:
            if self._submit_executor is None:
                self._submit_executor = ThreadPoolExecutor(max_workers=1)

        def work() -> None:
            all_ids: list[str] = []
            try:
                for url in urls:
                    self._log(f"解析播放列表: {url[:80]}…")
                    merged = self._resolve_urls(url, expand_playlist)
                    all_ids.extend(self._enqueue_urls(merged))
                self._log(f"已从 {len(urls)} 个列表加入 {len(all_ids)} 个下载任务")
                if self.on_enqueue_finished:
                    self.on_enqueue_finished(label, all_ids)
            except Exception as e:
                self._log(f"批量提交失败: {strip_ansi(str(e))}")
                if self.on_enqueue_finished:
                    self.on_enqueue_finished(label, all_ids)

        self._submit_executor.submit(work)

    def iter_tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    def count_active_tasks(self) -> tuple[int, int, int]:
        """(downloading, merging, queued) — 用于关闭窗口前的提示。"""
        downloading = merging = queued = 0
        for task in self._tasks.values():
            if task.status == TaskStatus.DOWNLOADING:
                downloading += 1
            elif task.status == TaskStatus.MERGING:
                merging += 1
            elif task.status == TaskStatus.QUEUED:
                queued += 1
        return downloading, merging, queued

    def has_active_downloads(self) -> bool:
        d, m, q = self.count_active_tasks()
        return (d + m + q) > 0

    def get_task(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def remove_tasks_where(self, pred) -> list[str]:
        removed: list[str] = []
        with self._lock:
            for tid, task in list(self._tasks.items()):
                if pred(task):
                    removed.append(tid)
                    self._cancel.pop(tid, None)
                    self._pause_pending.discard(tid)
                    del self._tasks[tid]
        return removed

    def retry_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in (
            TaskStatus.QUEUED,
            TaskStatus.DOWNLOADING,
            TaskStatus.MERGING,
        ):
            return False
        ev = self._cancel.get(task_id)
        if ev:
            ev.clear()
        resume = task.status in (TaskStatus.CANCELLED, TaskStatus.PAUSED)
        task.status = TaskStatus.QUEUED
        if not resume:
            task.progress = 0.0
            task.output_path = ""
        task.speed = ""
        task.error = ""
        with self._lock:
            self._pause_pending.discard(task_id)
        self._emit(task, force=True)
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self._futures.append(self._executor.submit(self._run_one, task_id))
        return True

    def resume_task(self, task_id: str) -> bool:
        return self.retry_task(task_id)

    def pause_all(self) -> int:
        """Pause every queued / active task."""
        n = 0
        for task in list(self._tasks.values()):
            if self.pause_task(task.task_id):
                n += 1
        if n:
            self._log(f"已全部暂停 {n} 个任务")
        return n

    def resume_all(self) -> int:
        """Resume every paused task (断点续传)."""
        n = 0
        for task in list(self._tasks.values()):
            if task.status != TaskStatus.PAUSED:
                continue
            if self.resume_task(task.task_id):
                n += 1
        if n:
            self._log(f"已全部继续 {n} 个任务")
        return n

    def pause_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status not in (
            TaskStatus.QUEUED,
            TaskStatus.DOWNLOADING,
            TaskStatus.MERGING,
        ):
            return False
        with self._lock:
            self._pause_pending.add(task_id)
        if task.status == TaskStatus.QUEUED:
            self._set_status(task, TaskStatus.PAUSED)
            return True
        ev = self._cancel.get(task_id)
        if ev:
            ev.set()
        return True

    def cancel_task(self, task_id: str) -> None:
        with self._lock:
            self._pause_pending.discard(task_id)
        ev = self._cancel.get(task_id)
        if ev:
            ev.set()
        task = self._tasks.get(task_id)
        if task and task.status not in (TaskStatus.FINISHED, TaskStatus.ERROR):
            if task.status not in (TaskStatus.DOWNLOADING, TaskStatus.MERGING):
                task.status = TaskStatus.CANCELLED
                self._emit(task, force=True)

    def _run_one(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        if task.status == TaskStatus.PAUSED:
            return
        cancel = self._cancel.get(task_id)
        if cancel is None:
            return
        self._set_status(task, TaskStatus.DOWNLOADING)
        self._log(f"[{task_id}] 开始: {task.url}")

        def on_progress(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                if total:
                    task.progress = min(100.0, done * 100.0 / total)
                task.speed = d.get("_speed_str") or ""
                task.eta = d.get("_eta_str") or ""
                self._emit(task)
            elif d.get("status") == "finished":
                fname = d.get("filename") or d.get("info_dict", {}).get("_filename")
                if fname:
                    task.output_path = str(fname)
                task.progress = 100.0
                self._set_status(task, TaskStatus.MERGING)

        opts = build_ydl_opts(
            self.output_dir,
            self.format_key,
            self.auth,
            on_progress=on_progress,
            cancel_event=cancel,
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(task.url, download=False)
                if info:
                    task.title = info.get("title") or task.url
                    self._emit(task, force=True)
                ydl.download([task.url])
                if info and not cancel.is_set():
                    try:
                        task.output_path = ydl.prepare_filename(info)
                    except Exception:
                        pass
            if cancel.is_set():
                self._on_download_stopped(task_id, task)
            else:
                self._set_status(task, TaskStatus.FINISHED)
                task.progress = 100.0
                self._emit(task, force=True)
                self._log(f"[{task_id}] 完成: {task.title}")
        except yt_dlp.utils.DownloadCancelled:
            self._on_download_stopped(task_id, task)
        except Exception as e:
            err = strip_ansi(str(e))
            if is_video_unavailable_error(err):
                task.error = brief_video_unavailable_message(err)
                self._set_status(task, TaskStatus.ERROR)
                self._log(f"[{task_id}] 不可用: {task.error}")
                return
            if "requested format is not available" in err.lower():
                self._log(f"[{task_id}] 当前画质不可用，改用通用格式重试…")
                try:
                    opts = build_ydl_opts_with_format(
                        self.output_dir,
                        self.format_key,
                        self.auth,
                        format_override=FORMAT_FALLBACK,
                        on_progress=on_progress,
                        cancel_event=cancel,
                    )
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([task.url])
                    if not cancel.is_set():
                        self._set_status(task, TaskStatus.FINISHED)
                        task.progress = 100.0
                        self._emit(task, force=True)
                        self._log(f"[{task_id}] 完成（已自动降级画质格式）")
                        return
                except Exception as retry_fmt:
                    err = strip_ansi(str(retry_fmt))
            if (
                self.auth.mode != "none"
                and not is_login_required_message(err)
                and (
                    is_format_unavailable(err) or "please sign in" in err.lower()
                )
            ):
                self._log(
                    f"[{task_id}] 登录 Cookie 可能导致格式列表异常，尝试不登录下载…"
                )
                try:
                    opts = build_ydl_opts_with_format(
                        self.output_dir,
                        self.format_key,
                        AuthConfig(mode="none"),
                        format_override=FORMAT_FALLBACK,
                        on_progress=on_progress,
                        cancel_event=cancel,
                    )
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([task.url])
                    if not cancel.is_set():
                        self._set_status(task, TaskStatus.FINISHED)
                        task.progress = 100.0
                        self._emit(task, force=True)
                        self._log(f"[{task_id}] 完成（公开视频，未使用 Cookie）")
                        return
                except Exception as retry_nc:
                    err = strip_ansi(str(retry_nc))
            if (
                self.auth.mode != "none"
                and is_cookie_infrastructure_error(err)
                and not is_login_required_message(err)
            ):
                self._log(
                    f"[{task_id}] Cookie 读取失败，尝试不登录下载公开视频…"
                )
                try:
                    opts = build_ydl_opts(
                        self.output_dir,
                        self.format_key,
                        AuthConfig(mode="none"),
                        on_progress=on_progress,
                        cancel_event=cancel,
                    )
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([task.url])
                    if not cancel.is_set():
                        self._set_status(task, TaskStatus.FINISHED)
                        task.progress = 100.0
                        self._emit(task, force=True)
                        self._log(f"[{task_id}] 完成（未使用登录态）")
                        return
                except Exception as retry_e:
                    err = strip_ansi(str(retry_e))
            err = format_youtube_auth_hint(
                err, self.auth.mode, self.auth.cookies_will_be_sent()
            )
            task.error = err
            self._set_status(task, TaskStatus.ERROR)
            self._log(f"[{task_id}] 失败: {err}")

    def shutdown(self, wait: bool = True) -> None:
        if self._submit_executor:
            self._submit_executor.shutdown(wait=wait, cancel_futures=not wait)
            self._submit_executor = None
        if self._executor:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
            self._executor = None