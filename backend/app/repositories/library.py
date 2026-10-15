from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.spotify.models import SourceArtist, SourceOccurrence, SourceTrack
from app.models import Artist, Playlist, PlaylistTrack, SourceType, Track, TrackArtist
from app.schemas.catalogue import LibraryStats, SourceEntries, SourceList, SourceSummary


class LibraryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def stats(self) -> LibraryStats:
        source_ids = select(Playlist.id).where(
            Playlist.last_synced_at.is_not(None), Playlist.source_type != SourceType.GENERATED
        )
        all_entries, available, tracks = self.session.execute(
            select(
                func.count(),
                func.count(PlaylistTrack.track_id),
                func.count(func.distinct(PlaylistTrack.track_id)),
            ).where(PlaylistTrack.playlist_id.in_(source_ids))
        ).one()
        track_ids = select(PlaylistTrack.track_id).where(PlaylistTrack.playlist_id.in_(source_ids))
        artists = (
            self.session.scalar(
                select(func.count(func.distinct(TrackArtist.artist_id))).where(
                    TrackArtist.track_id.in_(track_ids)
                )
            )
            or 0
        )
        playlists = (
            self.session.scalar(select(func.count()).select_from(source_ids.subquery())) or 0
        )
        return LibraryStats(
            source_playlists=playlists,
            playlist_entries=all_entries,
            readable_occurrences=available,
            unavailable_entries=all_entries - available,
            unique_tracks=tracks,
            duplicate_occurrences=available - tracks,
            unique_artists=artists,
        )

    def sources(self, offset: int, limit: int) -> SourceList:
        playlists = self.session.scalars(
            select(Playlist).order_by(Playlist.id).offset(offset).limit(limit)
        ).all()
        items: list[SourceSummary] = []
        for playlist in playlists:
            total, available = self.session.execute(
                select(func.count(), func.count(PlaylistTrack.track_id)).where(
                    PlaylistTrack.playlist_id == playlist.id
                )
            ).one()
            items.append(
                SourceSummary(
                    id=playlist.id,
                    spotify_playlist_id=playlist.spotify_playlist_id,
                    name=playlist.name,
                    spotify_owner_id=playlist.spotify_owner_id,
                    source_type=playlist.source_type.value,
                    snapshot_id=playlist.snapshot_id,
                    last_synced_at=playlist.last_synced_at,
                    playlist_entries=total,
                    unavailable_entries=total - available,
                )
            )
        return SourceList(
            total=self.session.scalar(select(func.count()).select_from(Playlist)) or 0, items=items
        )

    def entries(self, playlist_id: int, offset: int, limit: int) -> SourceEntries | None:
        if self.session.get(Playlist, playlist_id) is None:
            return None
        rows = self.session.execute(
            select(PlaylistTrack, Track)
            .outerjoin(Track)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
            .offset(offset)
            .limit(limit)
        ).all()
        track_ids = {track.id for _, track in rows if track}
        artist_map: dict[int, list[SourceArtist]] = {}
        for track_id, artist in self.session.execute(
            select(TrackArtist.track_id, Artist)
            .join(Artist)
            .where(TrackArtist.track_id.in_(track_ids))
            .order_by(TrackArtist.position)
        ):
            artist_map.setdefault(track_id, []).append(
                SourceArtist(spotify_artist_id=artist.spotify_artist_id, name=artist.name)
            )
        items = [
            SourceOccurrence(
                position=entry.position,
                added_at=entry.added_at,
                added_by=entry.added_by,
                unavailable_reason=entry.unavailable_reason,
                raw_kind=entry.raw_kind,
                source_uri=entry.source_uri,
                track=SourceTrack(
                    spotify_track_id=track.spotify_track_id,
                    spotify_uri=track.spotify_uri,
                    name=track.name,
                    album_name=track.album_name,
                    duration_ms=track.duration_ms,
                    explicit=track.explicit,
                    isrc=track.isrc,
                    artists=artist_map.get(track.id, []),
                )
                if track
                else None,
            )
            for entry, track in rows
        ]
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == playlist_id)
            )
            or 0
        )
        return SourceEntries(total=total, offset=offset, limit=limit, items=items)
