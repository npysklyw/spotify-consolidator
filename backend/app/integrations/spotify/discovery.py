import ast
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.integrations.spotify.exceptions import SpotifyWebPlayerProtocolError
from app.integrations.spotify.http import SpotifyHTTP
from app.integrations.spotify.web_player_config import (
    BUNDLE_HOSTS,
    CONTENTS_OPERATION,
    METADATA_OPERATION,
    WEB_ORIGIN,
    WebPlayerConfig,
)

# A narrow data-literal grammar. Never evaluate or execute downloaded JavaScript.
_QUOTED = r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"""
_SECRET_RECORD = re.compile(
    r"\{\s*secret\s*:\s*(" + _QUOTED + r"|\[[\d,\s]+\])\s*,\s*version\s*:\s*(\d+)\s*\}"
)


@dataclass(frozen=True)
class ProtocolMaterial:
    version: int
    cipher: tuple[int, ...] = field(repr=False)
    query_hashes: dict[str, str]


class ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def parse_material(bundle: str, config: WebPlayerConfig) -> ProtocolMaterial:
    hashes: dict[str, str] = {}
    for operation, override in [
        (METADATA_OPERATION, config.metadata_hash),
        (CONTENTS_OPERATION, config.contents_hash),
    ]:
        # Operation registration observed in the public bundle: name, type, digest.
        digest = override
        if digest is None:
            match = re.search(
                re.escape('"' + operation + '"') + r'\s*,\s*"query"\s*,\s*"([a-f0-9]{64})"', bundle
            )
            if match:
                digest = match[1]
        if digest is None or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise SpotifyWebPlayerProtocolError(
                f"Cannot discover {operation} query hash; Web Player bundle format may have changed"
            )
        hashes[operation] = digest
    if config.totp_version is not None and config.totp_cipher is not None:
        return ProtocolMaterial(config.totp_version, config.totp_cipher, hashes)
    candidates: list[tuple[int, tuple[int, ...]]] = []
    for match in _SECRET_RECORD.finditer(bundle):
        # Only accept records beside the observed TOTP key transformation.
        if not re.search(r"%\s*33", bundle[match.end() : match.end() + 2000]):
            continue
        try:
            value = ast.literal_eval(match[1])
        except (SyntaxError, ValueError):
            continue
        raw = [ord(char) for char in value] if isinstance(value, str) else value
        if (
            isinstance(raw, list)
            and 1 <= len(raw) <= 256
            and all(type(byte) is int and 0 <= byte <= 255 for byte in raw)
        ):
            candidates.append((int(match[2]), tuple(raw)))
    if not candidates:
        raise SpotifyWebPlayerProtocolError(
            "Cannot discover TOTP material; update discovery or configure version/cipher overrides"
        )
    version, cipher = max(candidates)
    return ProtocolMaterial(version, cipher, hashes)


class WebPlayerDiscovery:
    def __init__(self, http: SpotifyHTTP, config: WebPlayerConfig) -> None:
        self.http = http
        self.config = config
        self.cached: ProtocolMaterial | None = None
        self.expires = 0.0

    def invalidate(self) -> None:
        self.cached = None
        self.expires = 0

    async def get(self) -> ProtocolMaterial:
        if self.cached and time.monotonic() < self.expires:
            return self.cached
        config = self.config
        if all(
            (config.totp_version, config.totp_cipher, config.metadata_hash, config.contents_hash)
        ):
            material = parse_material("", config)
        else:
            page = await self.http.request("GET", WEB_ORIGIN + "/")
            if page.status_code != 200:
                raise SpotifyWebPlayerProtocolError("Web Player bootstrap page is unavailable")
            parser = ScriptParser()
            parser.feed(page.text)
            candidates = [
                urljoin(WEB_ORIGIN, source)
                for source in parser.sources
                if "/web-player/web-player." in source and urlsplit(source).path.endswith(".js")
            ]
            if not candidates:
                raise SpotifyWebPlayerProtocolError("Cannot locate the desktop Web Player bundle")
            url = candidates[0]
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.hostname not in BUNDLE_HOSTS
                or parts.username
                or parts.password
                or parts.port not in (None, 443)
            ):
                raise SpotifyWebPlayerProtocolError("Rejected untrusted Web Player bundle URL")
            bundle = await self.http.request("GET", url)
            if bundle.status_code != 200:
                raise SpotifyWebPlayerProtocolError("Web Player bundle is unavailable")
            material = parse_material(bundle.text, config)
        self.cached = material
        self.expires = time.monotonic() + config.discovery_ttl
        return material
