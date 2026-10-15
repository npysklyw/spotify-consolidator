from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.integrations.spotify.models import PlaylistMetadata, SourceOccurrence
from app.repositories.catalogue import (
    ArtistRepository,
    PlaylistOccurrenceRepository,
    PlaylistRepository,
    TrackRepository,
)
from app.services.deduplication import DeduplicationService


def persist_playlist(
    factory: sessionmaker[Session], metadata: PlaylistMetadata, entries: list[SourceOccurrence]
) -> int:
    """Called only after complete retrieval. A new transaction belongs to this playlist alone."""
    if len(entries) != metadata.total_entries or any(
        entry.position != index for index, entry in enumerate(entries)
    ):
        raise ValueError("Playlist positions or total are incomplete")
    sources = DeduplicationService().canonical_tracks(entries)
    with factory.begin() as session:
        playlist = PlaylistRepository(session).upsert(metadata, datetime.now(UTC))
        artists = ArtistRepository(
            session, (a.spotify_artist_id for t in sources.values() for a in t.artists)
        )
        tracks = TrackRepository(session, sources)
        associations = {}
        for key, source in sources.items():
            tracks.upsert(source)
            # Same artist listed twice must not break canonical artist membership.
            unique_artists = {artist.spotify_artist_id: artist for artist in source.artists}
            associations[key] = [artists.upsert(a) for a in unique_artists.values()]
        session.flush()
        for key, ordered_artists in associations.items():
            tracks.replace_artists(tracks.cache[key], ordered_artists)
        PlaylistOccurrenceRepository(session).replace(playlist.id, entries, tracks.cache)
        session.flush()
        return playlist.id
