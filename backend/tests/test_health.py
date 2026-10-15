from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_requires_no_spotify_credentials() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "spotify-consolidator",
        "stage": "foundation",
    }
