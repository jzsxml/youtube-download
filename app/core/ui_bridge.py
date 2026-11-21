from __future__ import annotations

import threading
import time


class ProgressThrottler:
    """Limit UI refresh rate from yt-dlp progress hooks (worker threads)."""

    def __init__(self, interval_sec: float = 0.25) -> None:
        self._interval = interval_sec
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, task_id: str, *, force: bool = False) -> bool:
        if force:
            return True
        now = time.monotonic()
        with self._lock:
            prev = self._last.get(task_id, 0.0)
            if now - prev < self._interval:
                return False
            self._last[task_id] = now
        return True