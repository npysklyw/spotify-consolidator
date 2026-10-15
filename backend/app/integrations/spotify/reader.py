from typing import Protocol

from app.integrations.spotify.models import PlaylistMetadata, SourceOccurrence


class PlaylistReader(Protocol):
    async def get_playlist(self, playlist_id: str) -> PlaylistMetadata:
        """Return validated metadata or raise a typed Spotify error."""
        ...

    async def get_playlist_tracks(self, playlist_id: str) -> list[SourceOccurrence]:
        """Return all ordered slots, including repeated and unavailable entries.

        Implementations must reject incomplete pagination instead of returning partial success.
        """
        ...
