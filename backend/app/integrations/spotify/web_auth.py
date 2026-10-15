import hashlib
import hmac
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

from app.integrations.spotify.discovery import WebPlayerDiscovery
from app.integrations.spotify.exceptions import (
    SpotifyAuthenticationError,
    SpotifyWebPlayerProtocolError,
)
from app.integrations.spotify.http import SpotifyHTTP, json_object
from app.integrations.spotify.web_player_config import TOKEN_URL, WEB_ORIGIN


def totp(cipher: tuple[int, ...], timestamp: float) -> str:
    """RFC 6238 SHA1, six digits; key encoding is the observed public client protocol."""
    key = "".join(str(byte ^ (9 + index % 33)) for index, byte in enumerate(cipher)).encode("ascii")
    counter = int(timestamp // 30).to_bytes(8, "big")
    digest = hmac.digest(key, counter, hashlib.sha1)
    offset = digest[-1] & 15
    number = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


@dataclass(frozen=True)
class WebToken:
    access_token: str = field(repr=False)
    client_id: str
    expires_at: float


class AnonymousWebTokenProvider:
    """Public Web Player access only. No account cookie or destination OAuth token."""

    def __init__(self, http: SpotifyHTTP, discovery: WebPlayerDiscovery) -> None:
        self.http = http
        self.discovery = discovery
        self.cached: WebToken | None = None

    def invalidate(self) -> None:
        self.cached = None

    async def get(self) -> WebToken:
        if self.cached and self.cached.expires_at > time.time() + 60:
            return self.cached
        for attempt, reason in enumerate(("transport", "init")):
            material = await self.discovery.get()
            clock = await self.http.request("HEAD", WEB_ORIGIN + "/")
            try:
                server_time = parsedate_to_datetime(clock.headers["Date"]).timestamp()
            except (KeyError, ValueError, TypeError, OverflowError):
                raise SpotifyWebPlayerProtocolError("Spotify server time is unavailable") from None
            code = totp(material.cipher, server_time)
            response = await self.http.request(
                "GET",
                TOKEN_URL,
                params={
                    "reason": reason,
                    "productType": "web-player",
                    "totp": code,
                    "totpServer": code,
                    "totpVer": str(material.version),
                },
                headers={
                    "App-Platform": "WebPlayer",
                    "Referer": WEB_ORIGIN + "/",
                    "Accept": "application/json",
                },
            )
            if response.status_code in {400, 401, 403}:
                if attempt == 0:
                    self.discovery.invalidate()
                    continue
                raise SpotifyAuthenticationError(
                    "Spotify rejected anonymous Web Player token acquisition"
                )
            if response.status_code != 200:
                raise SpotifyWebPlayerProtocolError("Unexpected Web Player token endpoint status")
            data = json_object(response)
            if data.get("totpVerExpired"):
                if attempt == 0:
                    self.discovery.invalidate()
                    continue
                raise SpotifyWebPlayerProtocolError("Spotify rejected the discovered TOTP version")
            token, client, expiry = (
                data.get(key)
                for key in ("accessToken", "clientId", "accessTokenExpirationTimestampMs")
            )
            if (
                not isinstance(token, str)
                or not token
                or not isinstance(client, str)
                or not client
                or not isinstance(expiry, (int, float))
                or isinstance(expiry, bool)
                or expiry <= time.time() * 1000 + 60_000
            ):
                raise SpotifyWebPlayerProtocolError(
                    "Web Player token response has missing/expired fields"
                )
            self.cached = WebToken(token, client, expiry / 1000)
            return self.cached
        raise SpotifyAuthenticationError("Could not acquire anonymous Web Player token")
