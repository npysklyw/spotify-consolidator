from app.integrations.spotify.models import SourceOccurrence, SourceTrack


class DeduplicationService:
    """Recording identity policy, independent of persistence and Spotify transport."""

    def canonical_tracks(self, entries: list[SourceOccurrence]) -> dict[str, SourceTrack]:
        return {entry.track.spotify_track_id: entry.track for entry in entries if entry.track}
