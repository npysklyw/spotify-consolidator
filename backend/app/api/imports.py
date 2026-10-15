from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.library import LibraryRepository
from app.schemas.catalogue import LibraryStats, SourceEntries, SourceList
from app.schemas.imports import ImportResult, PublicPlaylistImportRequest

router = APIRouter()
PageOffset = Annotated[int, Query(ge=0)]
PageLimit = Annotated[int, Query(ge=1, le=200)]


@router.post("/import/public-playlists", response_model=ImportResult)
async def import_public(payload: PublicPlaylistImportRequest, request: Request) -> ImportResult:
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.settings.allowed_origins:
        raise HTTPException(403, "Untrusted browser origin")
    if request.app.state.import_lock.locked():
        raise HTTPException(
            409, "An import is already running. Wait for it to finish before retrying."
        )
    async with request.app.state.import_lock:
        result: ImportResult = await request.app.state.import_service.import_public(
            payload.playlists
        )
        return result


@router.get("/library/stats", response_model=LibraryStats)
def library_stats(request: Request) -> LibraryStats:
    try:
        with request.app.state.sessions() as session:
            return LibraryRepository(session).stats()
    except SQLAlchemyError:
        raise HTTPException(
            503, "Database unavailable. Run make migrate and check configuration."
        ) from None


@router.get("/sources", response_model=SourceList)
def sources(request: Request, offset: PageOffset = 0, limit: PageLimit = 100) -> SourceList:
    try:
        with request.app.state.sessions() as session:
            return LibraryRepository(session).sources(offset, limit)
    except SQLAlchemyError:
        raise HTTPException(
            503, "Database unavailable. Run make migrate and check configuration."
        ) from None


@router.get("/sources/{playlist_id}/entries", response_model=SourceEntries)
def source_entries(
    playlist_id: int, request: Request, offset: PageOffset = 0, limit: PageLimit = 100
) -> SourceEntries:
    try:
        with request.app.state.sessions() as session:
            result = LibraryRepository(session).entries(playlist_id, offset, limit)
    except SQLAlchemyError:
        raise HTTPException(
            503, "Database unavailable. Run make migrate and check configuration."
        ) from None
    if result is None:
        raise HTTPException(404, "Imported source not found")
    return result
