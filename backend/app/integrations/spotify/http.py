import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.integrations.spotify.exceptions import (
    SpotifyRateLimitError,
    SpotifyTransportError,
    SpotifyWebPlayerProtocolError,
)
from app.integrations.spotify.web_player_config import USER_AGENT, WebPlayerConfig


class SpotifyHTTP:
    def __init__(
        self,
        client: httpx.AsyncClient,
        config: WebPlayerConfig,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.config = config
        self.sleep = sleep

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            try:
                async with self.client.stream(
                    method,
                    url,
                    params=params,
                    json=payload,
                    headers={"User-Agent": USER_AGENT, **(headers or {})},
                    timeout=self.config.request_timeout,
                    follow_redirects=False,
                ) as streamed:
                    body = bytearray()
                    async for chunk in streamed.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.config.max_response_bytes:
                            raise SpotifyWebPlayerProtocolError(
                                "Spotify response exceeded size limit"
                            )
                    # Rebuild with decoded bytes; avoid decoding Content-Encoding a second time.
                    response = httpx.Response(
                        streamed.status_code,
                        content=bytes(body),
                        headers={
                            k: v
                            for k, v in streamed.headers.items()
                            if k.lower() not in {"content-encoding", "content-length"}
                        },
                        request=streamed.request,
                    )
            except httpx.RequestError:
                if attempt == self.config.max_retries:
                    raise SpotifyTransportError(
                        "Spotify connection failed after bounded retries"
                    ) from None
                await self.sleep(0.5 * 2**attempt + random.random() * 0.2)
                continue
            if response.status_code == 429:
                delay = retry_after(response.headers.get("Retry-After"))
                if delay > self.config.max_retry_after or attempt == self.config.max_retries:
                    raise SpotifyRateLimitError(delay)
                await self.sleep(delay)
                continue
            if response.status_code >= 500:
                if attempt == self.config.max_retries:
                    raise SpotifyTransportError("Spotify service is temporarily unavailable")
                await self.sleep(0.5 * 2**attempt + random.random() * 0.2)
                continue
            if 300 <= response.status_code < 400:
                raise SpotifyWebPlayerProtocolError("Spotify returned an unexpected redirect")
            return response
        raise SpotifyTransportError("Spotify request exhausted its retry budget")


def retry_after(value: str | None) -> float:
    if value:
        try:
            seconds = float(value)
            if 0 <= seconds < float("inf"):
                return seconds
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return 5


def json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value: Any = response.json()
    except ValueError:
        raise SpotifyWebPlayerProtocolError("Spotify returned invalid JSON") from None
    if not isinstance(value, dict):
        raise SpotifyWebPlayerProtocolError("Spotify returned an unexpected JSON structure")
    return value
