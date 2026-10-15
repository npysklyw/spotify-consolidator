from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )

    database_url: str = "sqlite:///./spotify_consolidator.db"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    web_totp_version: int | None = None
    web_totp_cipher: tuple[int, ...] | None = Field(default=None, repr=False)
    web_metadata_hash: str | None = None
    web_contents_hash: str | None = None
    spotify_client_id: str = ""
    spotify_client_secret: SecretStr = SecretStr("")
    spotify_redirect_uri: str = "http://127.0.0.1:8000/api/spotify/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
