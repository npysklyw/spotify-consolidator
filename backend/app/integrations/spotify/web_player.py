from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.integrations.spotify.discovery import WebPlayerDiscovery
from app.integrations.spotify.exceptions import (
    SpotifyAuthenticationError,
    SpotifyPlaylistChangedError,
    SpotifyPlaylistRestrictedError,
    SpotifyWebPlayerProtocolError,
)
from app.integrations.spotify.http import SpotifyHTTP, json_object
from app.integrations.spotify.models import (
    PlaylistMetadata,
    SourceArtist,
    SourceOccurrence,
    SourceTrack,
)
from app.integrations.spotify.parsing import parse_playlist_id
from app.integrations.spotify.web_auth import AnonymousWebTokenProvider
from app.integrations.spotify.web_player_config import (
    CONTENTS_OPERATION,
    METADATA_OPERATION,
    QUERY_URL,
    WebPlayerConfig,
)


def obj(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpotifyWebPlayerProtocolError(f"Missing or malformed Web Player {field}")
    return value


def nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpotifyWebPlayerProtocolError(f"Missing or malformed Web Player {field}")
    return value


def spotify_id(uri: Any, kind: str) -> str:
    value = nonempty(uri, f"{kind} URI")
    prefix = f"spotify:{kind}:"
    if not value.startswith(prefix) or not value.removeprefix(prefix):
        raise SpotifyWebPlayerProtocolError(f"Malformed Spotify {kind} URI")
    return value.removeprefix(prefix)


def count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise SpotifyWebPlayerProtocolError("Missing or malformed playlist entry count")
    return int(value)


def metadata_from_json(data: dict[str, Any], identifier: str) -> PlaylistMetadata:
    owner = obj(obj(data.get("ownerV2"), "ownerV2").get("data"), "playlist owner")
    content = obj(data.get("content"), "playlist content")
    public = data.get("public")
    if public is not None and not isinstance(public, bool):
        raise SpotifyWebPlayerProtocolError("Malformed playlist visibility")
    attributes = data.get("attributes") or []
    collaborative = any(
        isinstance(a, dict)
        and a.get("key") == "collaborative"
        and str(a.get("value")).lower() == "true"
        for a in attributes
    )
    return PlaylistMetadata(
        spotify_playlist_id=identifier,
        spotify_owner_id=spotify_id(owner.get("uri"), "user"),
        name=nonempty(data.get("name"), "playlist name"),
        description=data.get("description") or "",
        public=public,
        collaborative=collaborative,
        snapshot_id=data.get("revisionId"),
        total_entries=count(content.get("totalCount")),
    )


def occurrence_from_json(value: Any, position: int) -> SourceOccurrence:
    item = obj(value, "playlist item")
    timestamp = obj(item.get("addedAt") or {}, "addedAt").get("isoString")
    added_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if timestamp else None
    added_by_data = obj(obj(item.get("addedBy") or {}, "addedBy").get("data") or {}, "addedBy data")
    added_by = added_by_data.get("username")
    if not added_by and added_by_data.get("uri"):
        added_by = spotify_id(added_by_data["uri"], "user")
    wrapped = obj(item.get("itemV2"), "itemV2")
    data = wrapped.get("data")
    if data is None:
        return SourceOccurrence(
            position=position,
            added_at=added_at,
            added_by=added_by,
            unavailable_reason="unavailable",
            raw_kind="null",
        )
    data = obj(data, "itemV2 data")
    kind = data.get("__typename")
    uri = data.get("uri")
    unavailable = {
        "NotFound": "deleted_or_unavailable",
        "RestrictedContent": "restricted",
        "LocalTrack": "local_file",
        "Episode": "non_track",
        "Chapter": "non_track",
        "PodcastEpisode": "non_track",
        "AudiobookChapter": "non_track",
    }
    reason = unavailable.get(kind) if isinstance(kind, str) else None
    if isinstance(uri, str) and uri.startswith("spotify:local:"):
        reason = "local_file"
    playability = obj(data.get("playability") or {}, "playability")
    if playability.get("playable") is False:
        reason = (
            "country_restricted"
            if playability.get("reason") == "COUNTRY_RESTRICTED"
            else "unplayable"
        )
    if reason:
        return SourceOccurrence(
            position=position,
            added_at=added_at,
            added_by=added_by,
            unavailable_reason=reason,
            raw_kind=kind or "LocalTrack",
            source_uri=uri if isinstance(uri, str) else None,
        )
    if kind not in (None, "Track"):
        raise SpotifyWebPlayerProtocolError("Unknown Web Player item kind; refusing a lossy import")
    identifier = spotify_id(uri, "track")
    artist_items = obj(data.get("artists"), "track artists").get("items")
    if not isinstance(artist_items, list):
        raise SpotifyWebPlayerProtocolError("Malformed Web Player artist list")
    artists = [
        SourceArtist(
            spotify_artist_id=spotify_id(obj(artist, "artist").get("uri"), "artist"),
            name=nonempty(obj(artist.get("profile"), "artist profile").get("name"), "artist name"),
        )
        for artist in artist_items
    ]
    rating = obj(data.get("contentRating") or {}, "contentRating").get("label")
    explicit = True if rating == "EXPLICIT" else False if rating in {"NONE", "CLEAN"} else None
    album = obj(data.get("albumOfTrack") or {}, "albumOfTrack")
    duration = obj(data.get("trackDuration") or {}, "trackDuration").get("totalMilliseconds")
    external = obj(data.get("externalIds") or {}, "externalIds")
    track = SourceTrack(
        spotify_track_id=identifier,
        spotify_uri=nonempty(uri, "track URI"),
        name=nonempty(data.get("name"), "track name"),
        artists=artists,
        album_name=album.get("name"),
        duration_ms=duration,
        explicit=explicit,
        isrc=external.get("isrc"),
    )
    return SourceOccurrence(
        position=position,
        track=track,
        raw_kind=kind or "Track",
        source_uri=uri,
        added_at=added_at,
        added_by=added_by,
    )


class SpotifyWebPlayerClient:
    """Complete public-playlist reader. Caller owns the injected HTTP client's lifetime."""

    def __init__(self, client: httpx.AsyncClient, config: WebPlayerConfig | None = None) -> None:
        self.config = config or WebPlayerConfig()
        self.http = SpotifyHTTP(client, self.config)
        self.discovery = WebPlayerDiscovery(self.http, self.config)
        self.tokens = AnonymousWebTokenProvider(self.http, self.discovery)

    async def query(self, operation: str, variables: dict[str, Any]) -> dict[str, Any]:
        token_refreshed = hash_refreshed = False
        for _ in range(3):
            token = await self.tokens.get()
            material = await self.discovery.get()
            response = await self.http.request(
                "POST",
                QUERY_URL,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Client-Id": token.client_id,
                    "App-Platform": "WebPlayer",
                    "Accept": "application/json",
                },
                payload={
                    "operationName": operation,
                    "variables": variables,
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": material.query_hashes[operation],
                        }
                    },
                },
            )
            if response.status_code == 401:
                if not token_refreshed:
                    token_refreshed = True
                    self.tokens.invalidate()
                    continue
                raise SpotifyAuthenticationError("Web Player token rejected after refresh")
            if response.status_code in {403, 404}:
                raise SpotifyPlaylistRestrictedError("Public playlist is restricted or unavailable")
            if response.status_code != 200:
                raise SpotifyWebPlayerProtocolError(
                    "Unexpected Web Player playlist endpoint status"
                )
            body = json_object(response)
            errors = body.get("errors")
            if errors:
                # Classify errors without echoing remote text, which may contain tokens.
                diagnostic = str(errors).lower()
                if any(
                    marker in diagnostic
                    for marker in ("persistedquery", "persisted query", "sha256")
                ):
                    if not hash_refreshed:
                        hash_refreshed = True
                        self.discovery.invalidate()
                        continue
                    raise SpotifyWebPlayerProtocolError(
                        "Playlist query rejected after hash rediscovery"
                    )
                raise SpotifyWebPlayerProtocolError(
                    "Spotify returned GraphQL errors; no data imported"
                )
            root = obj(body.get("data"), "GraphQL data")
            if root.get("playlistV2") is None:
                raise SpotifyPlaylistRestrictedError("Public playlist is unavailable")
            playlist = obj(root["playlistV2"], "playlistV2")
            if playlist.get("__typename") in {"NotFound", "RestrictedContent"}:
                raise SpotifyPlaylistRestrictedError("Public playlist is restricted or unavailable")
            return playlist
        raise SpotifyWebPlayerProtocolError("Web Player refresh budget exhausted")

    async def get_playlist(self, playlist_id: str) -> PlaylistMetadata:
        identifier = parse_playlist_id(playlist_id)
        data = await self.query(
            METADATA_OPERATION,
            {
                "uri": f"spotify:playlist:{identifier}",
                "enableWatchFeedEntrypoint": False,
            },
        )
        try:
            metadata = metadata_from_json(data, identifier)
        except (ValidationError, ValueError, TypeError):
            raise SpotifyWebPlayerProtocolError("Malformed Web Player playlist metadata") from None
        if metadata.total_entries > self.config.max_entries:
            raise SpotifyWebPlayerProtocolError("Playlist exceeds the configured entry limit")
        return metadata

    async def get_playlist_tracks(self, playlist_id: str) -> list[SourceOccurrence]:
        identifier = parse_playlist_id(playlist_id)
        before = await self.get_playlist(identifier)
        entries: list[SourceOccurrence] = []
        seen_uids: set[str] = set()
        for _ in range(self.config.max_pages):
            if len(entries) == before.total_entries:
                break
            data = await self.query(
                CONTENTS_OPERATION,
                {
                    "uri": f"spotify:playlist:{identifier}",
                    "offset": len(entries),
                    "limit": self.config.page_size,
                    "includeEpisodeContentRatingsV2": False,
                },
            )
            content = obj(data.get("content"), "playlist content")
            if count(content.get("totalCount")) != before.total_entries:
                raise SpotifyPlaylistChangedError("Playlist length changed during pagination")
            revision = data.get("revisionId")
            if revision and before.snapshot_id and revision != before.snapshot_id:
                raise SpotifyPlaylistChangedError("Playlist revision changed during pagination")
            items = content.get("items")
            if not isinstance(items, list) or not items:
                raise SpotifyWebPlayerProtocolError(
                    "Playlist pagination ended before all slots arrived"
                )
            if (
                len(items) > self.config.page_size
                or len(entries) + len(items) > before.total_entries
            ):
                raise SpotifyWebPlayerProtocolError("Playlist page exceeded expected bounds")
            for item in items:
                uid = obj(item, "playlist item").get("uid")
                if isinstance(uid, str) and uid:
                    if uid in seen_uids:
                        raise SpotifyWebPlayerProtocolError("Repeated slot UID during pagination")
                    seen_uids.add(uid)
            offset = len(entries)
            try:
                entries.extend(
                    occurrence_from_json(item, offset + index) for index, item in enumerate(items)
                )
            except (ValidationError, ValueError, TypeError, AttributeError):
                raise SpotifyWebPlayerProtocolError("Malformed Web Player playlist item") from None
        if len(entries) != before.total_entries:
            raise SpotifyWebPlayerProtocolError("Playlist pagination exceeded its page limit")
        after = await self.get_playlist(identifier)
        if before.snapshot_id != after.snapshot_id or before.total_entries != after.total_entries:
            raise SpotifyPlaylistChangedError("Playlist changed before retrieval completed")
        return entries
