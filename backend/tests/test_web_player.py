import asyncio
import copy
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.integrations.spotify.discovery import WebPlayerDiscovery, parse_material
from app.integrations.spotify.exceptions import (
    SpotifyAuthenticationError,
    SpotifyPlaylistChangedError,
    SpotifyPlaylistRestrictedError,
    SpotifyRateLimitError,
    SpotifyTransportError,
    SpotifyWebPlayerProtocolError,
)
from app.integrations.spotify.http import SpotifyHTTP
from app.integrations.spotify.web_auth import totp
from app.integrations.spotify.web_player import SpotifyWebPlayerClient, occurrence_from_json
from app.integrations.spotify.web_player_config import CONTENTS_OPERATION, WebPlayerConfig

# Invented non-production token material and digests; no upstream fixtures/code used.
BUNDLE = (
    'register("fetchPlaylistMetadata","query","'
    + "a" * 64
    + '");'
    + 'register("fetchPlaylistContents","query","'
    + "b" * 64
    + '");'
    + 'const keys=[{secret:"test",version:1}]; transform=index%33;'
)
PAGE = (
    '<script src="https://open.spotifycdn.com/cdn/build/web-player/web-player.fixture.js"></script>'
)
FIXTURE = json.loads((Path(__file__).parent / "fixtures/web_playlist.json").read_text())


class WebFixture:
    def __init__(self) -> None:
        self.data = copy.deepcopy(FIXTURE)
        self.offsets: list[int] = []
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.bundle_calls = 0
        self.token_rejections = 0
        self.hash_rejections = 0
        self.empty_page = False
        self.changed = False
        self.blocked = False
        self.invalid_json = False
        self.unknown_kind = False
        self.repeat_uid = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Date": "Sun, 11 Oct 2026 12:00:00 GMT"})
        if request.url.path == "/":
            return httpx.Response(200, text=PAGE)
        if request.url.host == "open.spotifycdn.com":
            self.bundle_calls += 1
            return httpx.Response(200, text=BUNDLE)
        if request.url.path == "/api/token":
            self.token_calls += 1
            assert "Cookie" not in request.headers
            assert request.url.params["totpVer"] == "1"
            return httpx.Response(
                200,
                json={
                    "accessToken": "fixture-token",
                    "clientId": "fixture-client",
                    "accessTokenExpirationTimestampMs": (time.time() + 3600) * 1000,
                },
            )
        assert request.url.path == "/pathfinder/v2/query"
        if self.blocked:
            return httpx.Response(403)
        if self.invalid_json:
            return httpx.Response(200, text="not-json")
        if self.token_rejections:
            self.token_rejections -= 1
            return httpx.Response(401)
        if self.hash_rejections:
            self.hash_rejections -= 1
            return httpx.Response(200, json={"errors": [{"message": "PersistedQueryNotFound"}]})
        payload = json.loads(request.content)
        if payload["operationName"] != CONTENTS_OPERATION:
            result = copy.deepcopy(self.data["metadata"])
            if self.changed and self.offsets:
                result["data"]["playlistV2"]["revisionId"] = "changed"
            return httpx.Response(200, json=result)
        offset = payload["variables"]["offset"]
        self.offsets.append(offset)
        items = self.data["items"][offset : offset + payload["variables"]["limit"]]
        if self.empty_page and offset > 0:
            items = []
        if self.unknown_kind:
            items = [{"itemV2": {"data": {"__typename": "UnexpectedNewKind"}}}]
        if self.repeat_uid and offset > 0:
            items = [{**item, "uid": "slot1"} for item in items]
        return httpx.Response(
            200,
            json={
                "data": {
                    "playlistV2": {
                        "content": {"totalCount": 3, "items": items},
                        "revisionId": "revision-one",
                    }
                }
            },
        )


def read(fixture: WebFixture, config: WebPlayerConfig | None = None) -> Any:
    async def run() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture)) as client:
            reader = SpotifyWebPlayerClient(client, config or WebPlayerConfig(page_size=2))
            return await reader.get_playlist_tracks("sample")

    return asyncio.run(run())


def test_all_pages_and_duplicate_and_unavailable_slots() -> None:
    fixture = WebFixture()
    result = read(fixture)
    assert fixture.offsets == [0, 2]
    assert [entry.position for entry in result] == [0, 1, 2]
    assert result[0].track.spotify_track_id == result[1].track.spotify_track_id
    assert result[0].track.album_name == "Fixture album"
    assert result[0].track.explicit is True
    assert result[0].added_by == "fixture-owner"
    assert result[2].track is None
    assert result[2].unavailable_reason == "deleted_or_unavailable"
    assert fixture.token_calls == fixture.bundle_calls == 1


@pytest.mark.parametrize(
    "option, error",
    [
        ("empty_page", SpotifyWebPlayerProtocolError),
        ("changed", SpotifyPlaylistChangedError),
        ("blocked", SpotifyPlaylistRestrictedError),
        ("invalid_json", SpotifyWebPlayerProtocolError),
        ("unknown_kind", SpotifyWebPlayerProtocolError),
        ("repeat_uid", SpotifyWebPlayerProtocolError),
    ],
)
def test_incomplete_or_changed_or_unknown_data_fails(option: str, error: type[Exception]) -> None:
    fixture = WebFixture()
    setattr(fixture, option, True)
    with pytest.raises(error):
        read(fixture)


def test_empty_playlist_is_valid() -> None:
    fixture = WebFixture()
    fixture.data["metadata"]["data"]["playlistV2"]["content"]["totalCount"] = 0
    assert read(fixture) == []
    assert fixture.offsets == []


def test_token_and_hash_refresh_are_bounded() -> None:
    fixture = WebFixture()
    fixture.token_rejections = fixture.hash_rejections = 1
    assert len(read(fixture)) == 3
    assert fixture.token_calls == 2
    assert fixture.bundle_calls == 2
    fixture = WebFixture()
    fixture.token_rejections = 5
    with pytest.raises(SpotifyAuthenticationError):
        read(fixture)
    assert fixture.token_calls == 2
    fixture = WebFixture()
    fixture.hash_rejections = 5
    with pytest.raises(SpotifyWebPlayerProtocolError):
        read(fixture)
    assert fixture.bundle_calls == 2


def test_pagination_bound() -> None:
    with pytest.raises(SpotifyWebPlayerProtocolError, match="page limit"):
        read(WebFixture(), WebPlayerConfig(page_size=2, max_pages=1))


def test_restricted_placeholder_preserves_position_and_uri() -> None:
    # Real observed shape: country-restricted Track has empty title/artist and duration zero.
    item = {
        "itemV2": {
            "data": {
                "__typename": "Track",
                "name": "",
                "uri": "spotify:track:restricted",
                "artists": {"items": [{"uri": "spotify:artist:missing", "profile": {"name": ""}}]},
                "playability": {"playable": False, "reason": "COUNTRY_RESTRICTED"},
            }
        }
    }
    slot = occurrence_from_json(item, 403)
    assert slot.position == 403 and slot.track is None
    assert slot.unavailable_reason == "country_restricted"
    assert slot.source_uri == "spotify:track:restricted"


@pytest.mark.parametrize(
    "data, reason",
    [
        (None, "unavailable"),
        ({"__typename": "Episode"}, "non_track"),
        ({"__typename": "LocalTrack", "uri": "spotify:local:artist:album:title:12"}, "local_file"),
    ],
)
def test_non_track_slots(data: Any, reason: str) -> None:
    slot = occurrence_from_json({"itemV2": {"data": data}}, 0)
    assert slot.track is None and slot.unavailable_reason == reason


def test_rfc6238_vector() -> None:
    # Encoding yields the RFC test key b'12345678901234567890'. Six-digit truncation.
    cipher = tuple(int(char) ^ (9 + i % 33) for i, char in enumerate("12345678901234567890"))
    assert totp(cipher, 59) == "287082"


def test_discovery_is_data_only_and_requires_both_hashes() -> None:
    material = parse_material(BUNDLE, WebPlayerConfig())
    assert material.version == 1
    assert material.cipher == tuple(map(ord, "test"))
    with pytest.raises(SpotifyWebPlayerProtocolError):
        parse_material(BUNDLE.replace("fetchPlaylistMetadata", "changed"), WebPlayerConfig())


def test_reject_untrusted_discovered_host() -> None:
    async def run() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, text=PAGE.replace("open.spotifycdn.com", "untrusted.test"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            config = WebPlayerConfig()
            with pytest.raises(SpotifyWebPlayerProtocolError, match="untrusted"):
                await WebPlayerDiscovery(SpotifyHTTP(client, config), config).get()
        assert calls == ["https://open.spotify.com/"]

    asyncio.run(run())


def test_rate_limit_and_transient_errors() -> None:
    async def run() -> None:
        sleeps: list[float] = []

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        responses = [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200)]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: responses.pop(0))
        ) as client:
            assert (
                await SpotifyHTTP(client, WebPlayerConfig(), sleep).request(
                    "GET", "https://open.spotify.com/"
                )
            ).status_code == 200
        assert sleeps == [2]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "300"})
            )
        ) as client:
            with pytest.raises(SpotifyRateLimitError) as error:
                await SpotifyHTTP(client, WebPlayerConfig(), sleep).request(
                    "GET", "https://open.spotify.com/"
                )
            assert error.value.retry_after == 300
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))
        ) as client:
            with pytest.raises(SpotifyTransportError):
                await SpotifyHTTP(client, WebPlayerConfig(), sleep).request(
                    "GET", "https://open.spotify.com/"
                )
        assert len(sleeps) == 3  # one 429 sleep and two 5xx retries

    asyncio.run(run())


def test_response_size_limit() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="x" * 50))
        ) as client:
            with pytest.raises(SpotifyWebPlayerProtocolError, match="size limit"):
                await SpotifyHTTP(client, WebPlayerConfig(max_response_bytes=10)).request(
                    "GET", "https://open.spotify.com/"
                )

    asyncio.run(run())
