from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.spotify.models import (
    PlaylistMetadata,
    SourceArtist,
    SourceOccurrence,
    SourceTrack,
)
from app.models import Artist, Playlist, PlaylistTrack, SourceType, Track, TrackArtist


class PlaylistRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, metadata: PlaylistMetadata, synced_at: datetime) -> Playlist:
        playlist = self.session.scalar(
            select(Playlist).where(Playlist.spotify_playlist_id == metadata.spotify_playlist_id)
        )
        if playlist is None:
            playlist = Playlist(
                spotify_playlist_id=metadata.spotify_playlist_id,
                source_type=SourceType.PUBLIC_URL,
                destination_managed=False,
            )
            self.session.add(playlist)
        # Refresh never changes existing discovery origin or management flags.
        playlist.spotify_owner_id = metadata.spotify_owner_id
        playlist.name = metadata.name
        playlist.description = metadata.description
        playlist.public = metadata.public
        playlist.collaborative = metadata.collaborative
        playlist.snapshot_id = metadata.snapshot_id
        playlist.last_synced_at = synced_at
        self.session.flush()
        return playlist


class ArtistRepository:
    def __init__(self, session: Session, identifiers: Iterable[str]) -> None:
        self.session = session
        self.cache: dict[str, Artist] = {}
        ids = list(set(identifiers))
        for offset in range(0, len(ids), 500):
            for artist in session.scalars(
                select(Artist).where(Artist.spotify_artist_id.in_(ids[offset : offset + 500]))
            ):
                self.cache[artist.spotify_artist_id] = artist

    def upsert(self, source: SourceArtist) -> Artist:
        artist = self.cache.get(source.spotify_artist_id)
        if artist is None:
            artist = Artist(spotify_artist_id=source.spotify_artist_id, name=source.name)
            self.session.add(artist)
            self.cache[source.spotify_artist_id] = artist
        artist.name = source.name
        return artist


class TrackRepository:
    def __init__(self, session: Session, identifiers: Iterable[str]) -> None:
        self.session = session
        self.cache: dict[str, Track] = {}
        ids = list(set(identifiers))
        for offset in range(0, len(ids), 500):
            for track in session.scalars(
                select(Track).where(Track.spotify_track_id.in_(ids[offset : offset + 500]))
            ):
                self.cache[track.spotify_track_id] = track

    def upsert(self, source: SourceTrack) -> Track:
        track = self.cache.get(source.spotify_track_id)
        if track is None:
            track = Track(spotify_track_id=source.spotify_track_id)
            self.session.add(track)
            self.cache[source.spotify_track_id] = track
        track.spotify_uri = source.spotify_uri
        track.name = source.name
        # An internal API may omit fields the official API previously supplied.
        for field in ("album_name", "duration_ms", "explicit", "isrc"):
            value = getattr(source, field)
            if value is not None:
                setattr(track, field, value)
        return track

    def replace_artists(self, track: Track, artists: list[Artist]) -> None:
        self.session.execute(delete(TrackArtist).where(TrackArtist.track_id == track.id))
        self.session.add_all(
            TrackArtist(track_id=track.id, artist_id=artist.id, position=index)
            for index, artist in enumerate(artists)
        )


class PlaylistOccurrenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(
        self, playlist_id: int, entries: list[SourceOccurrence], tracks: dict[str, Track]
    ) -> None:
        self.session.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
        self.session.add_all(
            PlaylistTrack(
                playlist_id=playlist_id,
                track_id=tracks[entry.track.spotify_track_id].id if entry.track else None,
                position=entry.position,
                added_at=entry.added_at,
                added_by=entry.added_by,
                unavailable_reason=entry.unavailable_reason,
                raw_kind=entry.raw_kind,
                source_uri=entry.source_uri,
            )
            for entry in entries
        )
