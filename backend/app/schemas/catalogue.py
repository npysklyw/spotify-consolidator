from datetime import datetime

from pydantic import BaseModel

from app.integrations.spotify.models import SourceOccurrence


class LibraryStats(BaseModel):
    source_playlists: int
    playlist_entries: int
    readable_occurrences: int
    unavailable_entries: int
    unique_tracks: int
    duplicate_occurrences: int
    unique_artists: int


class SourceSummary(BaseModel):
    id: int
    spotify_playlist_id: str
    name: str
    spotify_owner_id: str
    source_type: str
    snapshot_id: str | None
    last_synced_at: datetime | None
    playlist_entries: int
    unavailable_entries: int


class SourceList(BaseModel):
    total: int
    items: list[SourceSummary]


class SourceEntries(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SourceOccurrence]
