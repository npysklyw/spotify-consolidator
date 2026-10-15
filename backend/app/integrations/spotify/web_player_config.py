from dataclasses import dataclass, field

WEB_ORIGIN = "https://open.spotify.com"
TOKEN_URL = f"{WEB_ORIGIN}/api/token"
QUERY_URL = "https://api-partner.spotify.com/pathfinder/v2/query"
BUNDLE_HOSTS = frozenset({"open.spotifycdn.com", "open.spotify.com"})
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
METADATA_OPERATION = "fetchPlaylistMetadata"
CONTENTS_OPERATION = "fetchPlaylistContents"


@dataclass(frozen=True)
class WebPlayerConfig:
    page_size: int = 100
    max_entries: int = 100_000
    max_pages: int = 2_000
    max_response_bytes: int = 16 * 1024 * 1024
    request_timeout: float = 30
    max_retries: int = 2
    max_retry_after: float = 10
    discovery_ttl: float = 3600
    # Optional operator overrides, paired. No secrets/hashes from upstream are bundled.
    totp_version: int | None = None
    totp_cipher: tuple[int, ...] | None = field(default=None, repr=False)
    metadata_hash: str | None = None
    contents_hash: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.page_size <= 100 or self.max_pages < 1 or self.max_entries < 0:
            raise ValueError("Invalid playlist pagination limits")
        if (self.totp_version is None) != (self.totp_cipher is None):
            raise ValueError("TOTP version and cipher overrides must be configured together")
        if self.totp_version is not None and (
            self.totp_version < 1
            or not self.totp_cipher
            or any(type(v) is not int or not 0 <= v <= 255 for v in self.totp_cipher)
        ):
            raise ValueError("Invalid TOTP configuration")
