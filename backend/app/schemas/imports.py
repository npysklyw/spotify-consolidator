from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicPlaylistImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    playlists: str | list[str]

    @field_validator("playlists")
    @classmethod
    def bounded_input(cls, value: str | list[str]) -> str | list[str]:
        lines = value.splitlines() if isinstance(value, str) else value
        if len(lines) > 300 or sum(len(line) for line in lines) > 100_000:
            raise ValueError("At most 300 input lines and 100,000 characters are allowed")
        if not any(line.strip() for line in lines):
            raise ValueError("Supply at least one playlist URL, URI or ID")
        return value


class PlaylistImportResult(BaseModel):
    input_line: int
    spotify_playlist_id: str | None = None
    status: Literal["success", "failed", "duplicate_input"]
    playlist_id: int | None = None
    name: str | None = None
    playlist_entries: int = 0
    unique_tracks: int = 0
    unavailable_entries: int = 0
    error_code: str | None = None
    message: str | None = None
    retry_after: float | None = None


class ImportResult(BaseModel):
    input_count: int = 0
    requested_playlists: int = 0
    successful_playlists: int = 0
    failed_playlists: int = 0
    duplicate_inputs: int = 0
    playlist_entries: int = 0
    readable_occurrences: int = 0
    unique_tracks: int = 0
    duplicate_occurrences: int = 0
    unavailable_entries: int = 0
    results: list[PlaylistImportResult] = Field(default_factory=list)
