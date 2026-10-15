import re
from urllib.parse import urlsplit

# Spotify IDs are base62. Accept short IDs as in the product examples;
# the remote service determines whether an otherwise valid identifier exists.
_IDENTIFIER = re.compile(r"[A-Za-z0-9]{1,64}")


def parse_playlist_id(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith("spotify:playlist:"):
        candidate = candidate.removeprefix("spotify:playlist:")
    elif "://" in candidate:
        url = urlsplit(candidate)
        if url.scheme != "https" or url.netloc != "open.spotify.com" or url.username is not None:
            raise ValueError("Expected an HTTPS open.spotify.com playlist URL")
        parts = url.path.strip("/").split("/")
        if len(parts) == 3 and re.fullmatch(r"intl-[a-zA-Z-]+", parts[0]):
            parts = parts[1:]
        if len(parts) != 2 or parts[0] != "playlist":
            raise ValueError("Expected a Spotify playlist URL")
        candidate = parts[1]
    if not _IDENTIFIER.fullmatch(candidate):
        raise ValueError("Expected a playlist ID, Spotify playlist URI, or playlist URL")
    return candidate
