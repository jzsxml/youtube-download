from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from app.core.auth import AuthConfig
from app.core.download_manager import DownloadManager, DownloadTask, TaskStatus


@pytest.fixture
def manager(tmp_path: Path) -> DownloadManager:
    return DownloadManager(
        output_dir=tmp_path,
        format_key="best",
        auth=AuthConfig(mode="none"),
        max_workers=1,
    )


def test_retry_blocks_while_queued(manager: DownloadManager) -> None:
    task_id = "abcd1234"
    manager._tasks[task_id] = DownloadTask(
        task_id=task_id, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    manager._tasks[task_id].status = TaskStatus.QUEUED
    manager._cancel[task_id] = Event()
    assert manager.retry_task(task_id) is False


def test_pause_queued_becomes_paused(manager: DownloadManager) -> None:
    task_id = "pausetest"
    task = DownloadTask(task_id=task_id, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    manager._tasks[task_id] = task
    manager._cancel[task_id] = Event()
    assert manager.pause_task(task_id) is True
    assert task.status == TaskStatus.PAUSED


@patch.object(DownloadManager, "_run_one", lambda *a, **k: None)
def test_retry_paused_requeues(manager: DownloadManager) -> None:
    task_id = "resume01"
    task = DownloadTask(task_id=task_id, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    task.status = TaskStatus.PAUSED
    task.progress = 42.0
    manager._tasks[task_id] = task
    manager._cancel[task_id] = Event()
    manager._executor = ThreadPoolExecutor(max_workers=1)
    try:
        assert manager.retry_task(task_id) is True
        assert task.status == TaskStatus.QUEUED
        assert task.progress == 42.0
    finally:
        manager.shutdown(wait=False)