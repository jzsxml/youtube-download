from app.core.playlist_library import (
    _entry_to_playlist,
    _normalize_channel_playlists_url,
    _parse_list_id,
    _dedupe,
    parse_playlist_url,
    PlaylistEntry,
)


def test_parse_list_id_from_url() -> None:
    assert _parse_list_id({"url": "https://www.youtube.com/playlist?list=PLabc123xyz"}) == "PLabc123xyz"


def test_normalize_channel_hint() -> None:
    assert (
        _normalize_channel_playlists_url("@SomeUser")
        == "https://www.youtube.com/@SomeUser/playlists"
    )
    assert (
        _normalize_channel_playlists_url("https://www.youtube.com/channel/UCxxxx")
        == "https://www.youtube.com/channel/UCxxxx/playlists"
    )


def test_entry_to_playlist() -> None:
    pl = _entry_to_playlist({"id": "PLtest", "title": "My List", "playlist_count": 12})
    assert pl is not None
    assert pl.playlist_id == "PLtest"
    assert pl.video_count == 12
    assert pl.url.endswith("list=PLtest")


def test_dedupe() -> None:
    a = PlaylistEntry("PLx", "a", "https://www.youtube.com/playlist?list=PLx")
    b = PlaylistEntry("PLx", "b", "https://www.youtube.com/playlist?list=PLx")
    out = _dedupe([a, b])
    assert len(out) == 1


def test_parse_playlist_url() -> None:
    pl = parse_playlist_url("https://www.youtube.com/playlist?list=PLmylist123")
    assert pl is not None
    assert pl.playlist_id == "PLmylist123"