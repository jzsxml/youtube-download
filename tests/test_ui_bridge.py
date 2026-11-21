from unittest.mock import patch

from app.core.ui_bridge import ProgressThrottler


def test_throttle_allows_force() -> None:
    t = ProgressThrottler(1.0)
    assert t.allow("x", force=True) is True


def test_throttle_rate_limit() -> None:
    t = ProgressThrottler(0.25)
    clock = iter([0.0, 0.1, 0.26])
    with patch("app.core.ui_bridge.time.monotonic", lambda: next(clock)):
        assert t.allow("a") is True
        assert t.allow("a") is False
        assert t.allow("a") is True