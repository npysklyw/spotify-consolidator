from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import migration_config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.db.session import make_engine
from app.integrations.spotify.models import (
    PlaylistMetadata,
    SourceArtist,
    SourceOccurrence,
    SourceTrack,
)
from app.models import Artist, Playlist, PlaylistTrack, Track, TrackArtist
from app.repositories.catalogue import PlaylistOccurrenceRepository
from app.services.persistence import persist_playlist


def sample(playlist_id: str = "sample") -> tuple[PlaylistMetadata, list[SourceOccurrence]]:
    track = SourceTrack(
        spotify_track_id="song1",
        spotify_uri="spotify:track:song1",
        name="One",
        artists=[SourceArtist(spotify_artist_id="artist1", name="Artist")],
    )
    return PlaylistMetadata(
        spotify_playlist_id=playlist_id,
        spotify_owner_id="owner",
        name="Sample",
        total_entries=3,
        snapshot_id="r1",
    ), [
        SourceOccurrence(position=0, track=track, raw_kind="Track"),
        SourceOccurrence(position=1, track=track, raw_kind="Track"),
        SourceOccurrence(position=2, unavailable_reason="deleted", raw_kind="NotFound"),
    ]


def test_reruns_and_cross_playlist_provenance(sessions: sessionmaker[Session]) -> None:
    persist_playlist(sessions, *sample())
    persist_playlist(sessions, *sample())
    persist_playlist(sessions, *sample("second"))
    with sessions() as session:
        for model, expected in [
            (Playlist, 2),
            (Track, 1),
            (Artist, 1),
            (PlaylistTrack, 6),
            (TrackArtist, 1),
        ]:
            assert session.scalar(select(func.count()).select_from(model)) == expected
        slots = session.scalars(select(PlaylistTrack).order_by(PlaylistTrack.id)).all()
        assert [entry.position for entry in slots] == [0, 1, 2, 0, 1, 2]
        assert slots[0].track_id == slots[1].track_id == slots[3].track_id
        assert slots[2].track_id is None
        assert slots[2].unavailable_reason == "deleted"


def test_refresh_replaces_membership_and_preserves_management(
    sessions: sessionmaker[Session],
) -> None:
    local_id = persist_playlist(sessions, *sample())
    with sessions.begin() as session:
        playlist = session.get(Playlist, local_id)
        assert playlist
        playlist.destination_managed = True
    metadata, entries = sample()
    metadata.name = "Renamed"
    metadata.snapshot_id = "r2"
    metadata.total_entries = 1
    persist_playlist(sessions, metadata, entries[:1])
    with sessions() as session:
        playlist = session.get(Playlist, local_id)
        assert playlist and playlist.name == "Renamed" and playlist.destination_managed
        assert playlist.snapshot_id == "r2"
        assert session.scalar(select(func.count()).select_from(PlaylistTrack)) == 1


def test_transaction_rollback_restores_previous_snapshot(sessions: sessionmaker[Session]) -> None:
    local_id = persist_playlist(sessions, *sample())
    metadata, entries = sample()
    metadata.name = "Should roll back"
    original = PlaylistOccurrenceRepository.replace

    def fail_after_replace(self: PlaylistOccurrenceRepository, *args: object) -> None:
        original(self, *args)  # type: ignore[arg-type]
        self.session.flush()
        raise RuntimeError("injected persistence failure")

    with patch.object(PlaylistOccurrenceRepository, "replace", fail_after_replace):
        with pytest.raises(RuntimeError):
            persist_playlist(sessions, metadata, entries)
    with sessions() as session:
        playlist = session.get(Playlist, local_id)
        assert playlist and playlist.name == "Sample"
        assert session.scalar(select(func.count()).select_from(PlaylistTrack)) == 3


def test_database_constraints(sessions: sessionmaker[Session]) -> None:
    local_id = persist_playlist(sessions, *sample())
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(PlaylistTrack(playlist_id=local_id, position=0, unavailable_reason="gone"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(PlaylistTrack(playlist_id=999, position=0, unavailable_reason="gone"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("UPDATE playlists SET source_type = 'invalid'"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(PlaylistTrack(playlist_id=local_id, position=8))


def test_migration_round_trip_and_model_parity(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = migration_config(url)
    command.upgrade(config, "head")
    command.check(config)
    engine = make_engine(url)
    assert "playlist_tracks" in inspect(engine).get_table_names()
    engine.dispose()
    command.downgrade(config, "base")
    engine = make_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
    command.upgrade(config, "head")
