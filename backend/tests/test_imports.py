import asyncio

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_persistence import sample

from app.core.config import Settings
from app.integrations.spotify.exceptions import SpotifyWebPlayerProtocolError
from app.integrations.spotify.models import PlaylistMetadata, SourceOccurrence
from app.main import create_app
from app.models import Playlist, PlaylistTrack
from app.repositories.library import LibraryRepository
from app.services.imports import ImportService


class FakeReader:
    def __init__(self) -> None:
        self.failures: set[str] = set()
        self.reads: list[str] = []
        self.incomplete = False
        self.changed = False
        self.metadata_reads = 0

    async def get_playlist(self, playlist_id: str) -> PlaylistMetadata:
        self.metadata_reads += 1
        metadata = sample(playlist_id)[0]
        if self.changed:
            metadata.snapshot_id = str(self.metadata_reads)
        return metadata

    async def get_playlist_tracks(self, playlist_id: str) -> list[SourceOccurrence]:
        self.reads.append(playlist_id)
        if playlist_id in self.failures:
            raise SpotifyWebPlayerProtocolError("Page retrieval failed")
        entries = sample(playlist_id)[1]
        return entries[:1] if self.incomplete else entries


def test_nine_of_ten_commit_independently(sessions: sessionmaker[Session]) -> None:
    reader = FakeReader()
    reader.failures = {"playlist4"}
    result = asyncio.run(
        ImportService(sessions, reader).import_public([f"playlist{i}" for i in range(1, 11)])
    )
    assert result.successful_playlists == 9 and result.failed_playlists == 1
    assert result.results[3].error_code == "SpotifyWebPlayerProtocolError"
    assert result.playlist_entries == 27
    assert result.readable_occurrences == 18
    assert result.unique_tracks == 1 and result.duplicate_occurrences == 17
    assert result.unavailable_entries == 9
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Playlist)) == 9
        assert session.scalar(select(func.count()).select_from(PlaylistTrack)) == 27
        assert LibraryRepository(session).stats().unique_tracks == 1


def test_equivalent_inputs_and_invalid_lines(sessions: sessionmaker[Session]) -> None:
    reader = FakeReader()
    result = asyncio.run(
        ImportService(sessions, reader).import_public(
            "sample\nspotify:playlist:sample\nhttps://open.spotify.com/playlist/sample?si=x\n\n!bad\nsecond"
        )
    )
    assert result.input_count == 5 and result.requested_playlists == 3
    assert result.duplicate_inputs == 2
    assert result.successful_playlists == 2 and result.failed_playlists == 1
    assert reader.reads == ["sample", "second"]


def test_failed_refresh_keeps_previous_snapshot(sessions: sessionmaker[Session]) -> None:
    reader = FakeReader()
    service = ImportService(sessions, reader)
    asyncio.run(service.import_public("sample"))
    reader.failures = {"sample"}
    assert asyncio.run(service.import_public("sample")).failed_playlists == 1
    reader.failures.clear()
    reader.incomplete = True
    assert asyncio.run(service.import_public("sample")).failed_playlists == 1
    reader.incomplete = False
    reader.changed = True
    assert asyncio.run(service.import_public("sample")).failed_playlists == 1
    with sessions() as session:
        playlist = session.scalar(select(Playlist))
        assert playlist and playlist.snapshot_id == "r1"
        assert session.scalar(select(func.count()).select_from(PlaylistTrack)) == 3


def test_api_import_and_inspection(sessions: sessionmaker[Session]) -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings.model_construct(), sessions=sessions, reader=FakeReader()
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://localhost"
            ) as client:
                stats = await client.get("/api/library/stats")
                assert stats.json()["source_playlists"] == 0
                response = await client.post(
                    "/api/import/public-playlists", json={"playlists": "sample\nsecond"}
                )
                assert response.status_code == 200
                assert response.json()["successful_playlists"] == 2
                rerun = await client.post(
                    "/api/import/public-playlists", json={"playlists": ["sample"]}
                )
                assert rerun.json()["successful_playlists"] == 1
                sources = (await client.get("/api/sources")).json()
                assert sources["total"] == 2
                source_id = sources["items"][0]["id"]
                entries = (
                    await client.get(f"/api/sources/{source_id}/entries?offset=1&limit=2")
                ).json()
                assert entries["total"] == 3
                assert [e["position"] for e in entries["items"]] == [1, 2]
                assert entries["items"][1]["unavailable_reason"] == "deleted"
                stats = await client.get("/api/library/stats")
                assert stats.json() == {
                    "source_playlists": 2,
                    "playlist_entries": 6,
                    "readable_occurrences": 4,
                    "unavailable_entries": 2,
                    "unique_tracks": 1,
                    "duplicate_occurrences": 3,
                    "unique_artists": 1,
                }
                assert (await client.get("/api/sources/999/entries")).status_code == 404
                assert (await client.get("/api/sources?limit=201")).status_code == 422
                assert (
                    await client.post("/api/import/public-playlists", json={"playlists": ""})
                ).status_code == 422
                forbidden = await client.post(
                    "/api/import/public-playlists",
                    json={"playlists": "sample"},
                    headers={"Origin": "https://untrusted.test"},
                )
                assert forbidden.status_code == 403
                # Foreign host requests are rejected before routing, protecting local mutations.
                assert (
                    await client.get("/api/sources", headers={"Host": "untrusted.test"})
                ).status_code == 400

    asyncio.run(run())


def test_malformed_request_is_bounded(sessions: sessionmaker[Session]) -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings.model_construct(), sessions=sessions, reader=FakeReader()
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://localhost"
            ) as client:
                for body in (
                    {"playlists": ["a"] * 301},
                    {"playlists": 123},
                    {"playlists": "x", "extra": "no"},
                ):
                    assert (
                        await client.post("/api/import/public-playlists", json=body)
                    ).status_code == 422

    asyncio.run(run())


def test_busy_import_returns_conflict(sessions: sessionmaker[Session]) -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings.model_construct(), sessions=sessions, reader=FakeReader()
        )
        async with app.router.lifespan_context(app):
            async with app.state.import_lock:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://localhost"
                ) as client:
                    response = await client.post(
                        "/api/import/public-playlists", json={"playlists": "sample"}
                    )
                    assert response.status_code == 409

    asyncio.run(run())
