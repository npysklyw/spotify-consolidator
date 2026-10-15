class SpotifyError(Exception):
    """Base for sanitized, user-reportable integration failures."""


class SpotifyAuthenticationError(SpotifyError):
    pass


class SpotifyPlaylistRestrictedError(SpotifyError):
    pass


class SpotifyWebPlayerProtocolError(SpotifyError):
    """The remote schema, token protocol, or persisted query has changed."""


class SpotifyRateLimitError(SpotifyError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__("Spotify rate limit reached; retry later.")


class SpotifyTransportError(SpotifyError):
    pass


class SpotifyPlaylistChangedError(SpotifyError):
    """A playlist changed while its pages were being retrieved."""
