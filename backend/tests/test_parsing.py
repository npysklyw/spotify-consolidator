import pytest

from app.integrations.spotify.parsing import parse_playlist_id


@pytest.mark.parametrize(
    "value",
    [
        "abc123",
        " spotify:playlist:abc123 ",
        "https://open.spotify.com/playlist/abc123?si=xyz",
        "https://open.spotify.com/intl-de/playlist/abc123/",
    ],
)
def test_playlist_forms(value: str) -> None:
    assert parse_playlist_id(value) == "abc123"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "abc 123",
        "spotify:track:abc123",
        "spotify:playlist:",
        "https://example.com/playlist/abc123",
        "https://open.spotify.com/track/abc123",
        "https://open.spotify.com.evil.test/playlist/abc123",
        "https://name@open.spotify.com/playlist/abc123",
        "http://open.spotify.com/playlist/abc123",
        "https://open.spotify.com/playlist/abc123/extra",
        "../abc123",
        "abc_123",
    ],
)
def test_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        parse_playlist_id(value)
