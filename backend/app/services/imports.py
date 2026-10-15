import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.integrations.spotify.exceptions import (
    SpotifyError,
    SpotifyPlaylistChangedError,
    SpotifyRateLimitError,
    SpotifyWebPlayerProtocolError,
)
from app.integrations.spotify.models import PlaylistMetadata, SourceOccurrence
from app.integrations.spotify.parsing import parse_playlist_id
from app.integrations.spotify.reader import PlaylistReader
from app.schemas.imports import ImportResult, PlaylistImportResult
from app.services.persistence import persist_playlist

logger = logging.getLogger(__name__)


class ImportService:
    def __init__(self, sessions: sessionmaker[Session], reader: PlaylistReader) -> None:
        self.sessions = sessions
        self.reader = reader

    async def retrieve(self, identifier: str) -> tuple[PlaylistMetadata, list[SourceOccurrence]]:
        for attempt in range(2):
            try:
                before = await self.reader.get_playlist(identifier)
                entries = await self.reader.get_playlist_tracks(identifier)
                after = await self.reader.get_playlist(identifier)
                if (
                    before.spotify_playlist_id != identifier
                    or after.spotify_playlist_id != identifier
                ):
                    raise SpotifyWebPlayerProtocolError("Reader returned a different playlist ID")
                if (
                    before.snapshot_id != after.snapshot_id
                    or before.total_entries != after.total_entries
                ):
                    raise SpotifyPlaylistChangedError("Playlist changed during retrieval")
                if len(entries) != after.total_entries or any(
                    entry.position != i for i, entry in enumerate(entries)
                ):
                    raise SpotifyWebPlayerProtocolError(
                        "Reader returned an incomplete occurrence set"
                    )
                return after, entries
            except SpotifyPlaylistChangedError:
                if attempt == 1:
                    raise
        raise SpotifyPlaylistChangedError("Playlist did not stabilize")

    async def import_public(self, values: str | list[str]) -> ImportResult:
        lines = values.splitlines() if isinstance(values, str) else values
        result = ImportResult(input_count=sum(bool(line.strip()) for line in lines))
        seen: set[str] = set()
        successful_tracks: set[str] = set()
        rate_limited: float | None = None
        for index, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                identifier = parse_playlist_id(line)
            except ValueError:
                result.requested_playlists += 1
                result.failed_playlists += 1
                result.results.append(
                    PlaylistImportResult(
                        input_line=index,
                        status="failed",
                        error_code="invalid_input",
                        message="Expected a Spotify playlist URL, URI or ID",
                    )
                )
                continue
            if identifier in seen:
                result.duplicate_inputs += 1
                result.results.append(
                    PlaylistImportResult(
                        input_line=index,
                        spotify_playlist_id=identifier,
                        status="duplicate_input",
                    )
                )
                continue
            seen.add(identifier)
            result.requested_playlists += 1
            item = PlaylistImportResult(
                input_line=index, spotify_playlist_id=identifier, status="failed"
            )
            try:
                if rate_limited is not None:
                    raise SpotifyRateLimitError(rate_limited)
                metadata, entries = await self.retrieve(identifier)
                # DB work is short and isolated; no transaction is open while awaiting Spotify.
                item.playlist_id = await asyncio.to_thread(
                    persist_playlist, self.sessions, metadata, entries
                )
                item.status = "success"
                item.name = metadata.name
                item.playlist_entries = len(entries)
                track_ids = {entry.track.spotify_track_id for entry in entries if entry.track}
                item.unique_tracks = len(track_ids)
                item.unavailable_entries = sum(entry.track is None for entry in entries)
                successful_tracks.update(track_ids)
                result.successful_playlists += 1
                result.playlist_entries += len(entries)
                result.unavailable_entries += item.unavailable_entries
            except SpotifyRateLimitError as error:
                # Do not hammer Spotify for each subsequent playlist in this batch.
                rate_limited = error.retry_after
                item.error_code = "rate_limited"
                item.message = "Spotify rate limit reached. Retry these playlists later."
                item.retry_after = error.retry_after
            except SpotifyError as error:
                item.error_code = type(error).__name__
                item.message = str(error)
            except SQLAlchemyError:
                item.error_code = "database_error"
                item.message = (
                    "Database transaction failed and was rolled back. Check migrations and retry."
                )
            except Exception as error:
                # Continue other playlists without exposing HTTP/DB secrets.
                logger.error("Playlist import failed with %s", type(error).__name__)
                item.error_code = "unexpected_error"
                item.message = "Unexpected import failure; this playlist was not changed."
            if item.status == "failed":
                result.failed_playlists += 1
            result.results.append(item)
        result.unique_tracks = len(successful_tracks)
        result.readable_occurrences = result.playlist_entries - result.unavailable_entries
        result.duplicate_occurrences = result.readable_occurrences - result.unique_tracks
        return result
