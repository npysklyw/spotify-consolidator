"""Explicit, local bulk import command. Never automatically reads personal sample files."""

import argparse
import asyncio
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.db.session import make_engine, session_factory
from app.integrations.spotify.web_player import SpotifyWebPlayerClient
from app.main import web_config
from app.schemas.imports import PublicPlaylistImportRequest
from app.services.imports import ImportService


async def run(path: Path) -> int:
    payload = PublicPlaylistImportRequest(playlists=path.read_text())
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        async with httpx.AsyncClient() as client:
            result = await ImportService(
                session_factory(engine), SpotifyWebPlayerClient(client, web_config(settings))
            ).import_public(payload.playlists)
            print(result.model_dump_json(indent=2))
            return 1 if result.failed_playlists else 0
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import public playlists into the local catalogue")
    parser.add_argument(
        "file", type=Path, help="UTF-8 file with one playlist URL, URI or ID per line"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.file)))


if __name__ == "__main__":
    main()
