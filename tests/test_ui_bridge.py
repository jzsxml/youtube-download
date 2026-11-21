import time

from app.core.ui_bridge import ProgressThrottler


def test_throttle_allows_force() -> None:
    t = ProgressThrottler(1.0)
    assert t.allow("x", force=True) is True


def test_throttle_rate_limit() -> None:
    t = ProgressThrottler(0.05)
    assert t.allow("a") is True
    assert t.allow("a") is False
    time.sleep(0.06)
    assert t.allow("a") is True