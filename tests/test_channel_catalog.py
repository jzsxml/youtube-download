from app.core.channel_catalog import (
    ChannelTab,
    filter_entries_by_title,
    normalize_channel_base,
    page_to_range,
    channel_tab_url,
    ChannelVideoEntry,
)


def test_page_to_range() -> None:
    assert page_to_range(1) == (1, 100)
    assert page_to_range(2) == (101, 200)


def test_normalize_channel_strips_tab() -> None:
    base = normalize_channel_base(
        "https://www.youtube.com/@Fireship/videos"
    )
    assert base == "https://www.youtube.com/@Fireship"
    assert (
        channel_tab_url(base, ChannelTab.SHORTS)
        == "https://www.youtube.com/@Fireship/shorts"
    )


def test_normalize_channel_handle_and_uc() -> None:
    assert normalize_channel_base("@Fireship") == "https://www.youtube.com/@Fireship"
    assert (
        normalize_channel_base("UC_x5XG1OV2P6uZZ5FSM9Ttw")
        == "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"
    )


def test_normalize_encoded_path() -> None:
    url = "https://www.youtube.com/@%E4%B8%89%E5%9C%8B/videos"
    base = normalize_channel_base(url)
    assert base is not None
    assert "/videos" not in base
    assert "@" in base


def test_filter_entries_by_title() -> None:
    entries = [
        ChannelVideoEntry("a", "Hello World", "https://youtu.be/a"),
        ChannelVideoEntry("b", "Short clip", "https://youtu.be/b"),
    ]
    assert len(filter_entries_by_title(entries, "hello")) == 1
    assert len(filter_entries_by_title(entries, "")) == 2