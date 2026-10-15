from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class SourceType(StrEnum):
    PUBLIC_URL = "public_url"
    DESTINATION_ACCOUNT = "destination_account"
    GENERATED = "generated"


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Playlist(Timestamps, Base):
    __tablename__ = "playlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_playlist_id: Mapped[str] = mapped_column(String(64), unique=True)
    spotify_owner_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    public: Mapped[bool | None] = mapped_column(Boolean)
    collaborative: Mapped[bool] = mapped_column(default=False, server_default=false())
    snapshot_id: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            values_callable=lambda values: [v.value for v in values],
            native_enum=False,
            create_constraint=True,
            name="source_type",
        ),
        default=SourceType.PUBLIC_URL,
    )
    destination_managed: Mapped[bool] = mapped_column(default=False, server_default=false())
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Track(Timestamps, Base):
    __tablename__ = "tracks"
    __table_args__ = (CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_track_id: Mapped[str] = mapped_column(String(64), unique=True)
    spotify_uri: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(Text)
    album_name: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    explicit: Mapped[bool | None] = mapped_column(Boolean)
    isrc: Mapped[str | None] = mapped_column(String(32), index=True)


class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_artist_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)


class TrackArtist(Base):
    __tablename__ = "track_artists"
    __table_args__ = (
        UniqueConstraint("track_id", "position", name="uq_track_artist_position"),
        CheckConstraint("position >= 0", name="artist_position"),
        Index("ix_track_artists_artist_id", "artist_id"),
    )
    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_playlist_position"),
        CheckConstraint("position >= 0", name="occurrence_position"),
        CheckConstraint(
            "(track_id IS NOT NULL AND unavailable_reason IS NULL) OR "
            "(track_id IS NULL AND unavailable_reason IS NOT NULL)",
            name="occurrence_state",
        ),
        Index("ix_playlist_tracks_track_id", "track_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"))
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    added_by: Mapped[str | None] = mapped_column(String(255))
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    raw_kind: Mapped[str | None] = mapped_column(String(100))
    source_uri: Mapped[str | None] = mapped_column(Text)
