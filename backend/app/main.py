import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.health import router as health_router
from app.api.imports import router as import_router
from app.core.config import Settings, get_settings
from app.db.session import make_engine, session_factory
from app.integrations.spotify.reader import PlaylistReader
from app.integrations.spotify.web_player import SpotifyWebPlayerClient
from app.integrations.spotify.web_player_config import WebPlayerConfig
from app.services.imports import ImportService


def web_config(settings: Settings) -> WebPlayerConfig:
    return WebPlayerConfig(
        totp_version=settings.web_totp_version,
        totp_cipher=settings.web_totp_cipher,
        metadata_hash=settings.web_metadata_hash,
        contents_hash=settings.web_contents_hash,
    )


def create_app(
    settings: Settings | None = None,
    reader: PlaylistReader | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url) if sessions is None else None
        if sessions is not None:
            factory = sessions
        else:
            assert engine is not None
            factory = session_factory(engine)
        async with httpx.AsyncClient() as client:
            application.state.settings = settings
            application.state.sessions = factory
            application.state.import_lock = asyncio.Lock()
            application.state.import_service = ImportService(
                factory, reader or SpotifyWebPlayerClient(client, web_config(settings))
            )
            try:
                yield
            finally:
                if engine is not None:
                    engine.dispose()

    application = FastAPI(title="Spotify Consolidator", version="0.2.0", lifespan=lifespan)
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", "backend"]
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(import_router, prefix="/api")
    return application


app = create_app()
