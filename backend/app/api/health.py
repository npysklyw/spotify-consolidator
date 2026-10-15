from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process liveness only. Does not claim database or Spotify readiness."""
    return HealthResponse()
