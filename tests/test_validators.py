import pytest

from app.core.validators import normalize_youtube_url, should_expand_playlist


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", None),
        ("  ", None),
        ("dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        (
            "https://www.youtube.com/watch?v=abc123def45&list=PLxyz",
            "https://www.youtube.com/watch?v=abc123def45&list=PLxyz",
        ),
        ("https://youtu.be/abc123def45", "https://www.youtube.com/watch?v=abc123def45"),
        ("https://evil.com/watch?v=x", None),
    ],
)
def test_normalize_youtube_url(raw: str, expected: str | None) -> None:
    assert normalize_youtube_url(raw) == expected


def test_should_expand_playlist_watch_with_list() -> None:
    url = "https://www.youtube.com/watch?v=abc123def45&list=PLtests"
    assert should_expand_playlist(url, True) is True
    assert should_expand_playlist(url, False) is False


def test_should_expand_playlist_single_watch() -> None:
    url = "https://www.youtube.com/watch?v=abc123def45"
    assert should_expand_playlist(url, True) is False