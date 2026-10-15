from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator


class SourceArtist(BaseModel):
    spotify_artist_id: str
    name: str


class SourceTrack(BaseModel):
    spotify_track_id: str
    spotify_uri: str
    name: str
    artists: list[SourceArtist]
    album_name: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    explicit: bool | None = None
    isrc: str | None = None


class SourceOccurrence(BaseModel):
    position: int = Field(ge=0)
    track: SourceTrack | None = None
    unavailable_reason: str | None = None
    raw_kind: str | None = None
    source_uri: str | None = None
    added_at: datetime | None = None
    added_by: str | None = None

    @model_validator(mode="after")
    def valid_slot(self) -> Self:
        if (self.track is None) != bool(self.unavailable_reason):
            raise ValueError("An unavailable slot needs a reason; a track slot must have no reason")
        return self


class PlaylistMetadata(BaseModel):
    spotify_playlist_id: str
    spotify_owner_id: str
    name: str
    description: str = ""
    public: bool | None = None
    collaborative: bool = False
    snapshot_id: str | None = None
    total_entries: int = Field(ge=0)
