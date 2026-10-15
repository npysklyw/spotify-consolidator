# Web Player protocol research

## Scope and provenance

Inspected `misiektoja/spotify_profile_monitor` on 2026-10-11:
[repository](https://github.com/misiektoja/spotify_profile_monitor) and
[implementation](https://github.com/misiektoja/spotify_profile_monitor/blob/main/spotify_profile_monitor.py).
The downloaded research file had SHA-256
`ea578234dbb96a401f200a711a28dc1fd8b36be63a5db86341981be56792f8cd`.
Upstream main is mutable; that checksum identifies the inspected bytes.

Upstream is GPL-3.0. No upstream source, tests, regular expressions, secret values or
query hashes have been copied into this project, and it is not a runtime dependency.
This note records protocol observations. The future adapter should be independently
implemented and tested against separately constructed protocol fixtures. Reassess
licensing before importing or adapting upstream implementation code. No project license
has been chosen on the user's behalf.

## Observed behavior

Official playlist access can be restricted; upstream supplements it with the Web Player.
The relevant functions inspected were `fetch_server_time`, `generate_totp`,
`refresh_access_token_from_sp_dc`, `spotify_get_web_access_token_data`,
`spotify_discover_playlist_query_hash`, `spotify_web_playlist_query`,
`spotify_get_playlist_info_web`, and both playlist backend selectors.

The public reader obtains an anonymous token separately from account authentication.
Token retrieval is a GET to `https://open.spotify.com/api/token`, with product type,
reason and versioned TOTP parameters. Upstream tries transport, then init. Authenticated
Web Player usage can supply an sp_dc cookie; its anonymous playlist route supplies none.
It validates token, expiry and client ID, caches them and refreshes before expiry.

TOTP is a six-digit code on a 30-second interval, derived from versioned client-side
cipher material. Upstream transforms that material into a TOTP key. Server time comes
from the Date header of a HEAD request to the Web Player page. Its secret and version
are configuration values refreshed with a separate secret-grabber tool; the inspected
playlist reader does not automatically discover rotating TOTP secrets. We must not
claim that putting an old secret in configuration solves rotation indefinitely.

Playlist reads POST persisted GraphQL operations to
`https://api-partner.spotify.com/pathfinder/v2/query`, with bearer token, client ID,
Web Player headers, operation name, variables and a SHA-256 persisted-query extension.
Operations observed: `fetchPlaylistMetadata` and `fetchPlaylistContents`. Data is under
`playlistV2`; contents include `content.items`, `totalCount`, and nested track/artist data.
Pagination uses offset/limit (100 in the reference), with URI and operation-specific flags.

Upstream discovers a playlist query hash in the Web Player JavaScript referenced by its
HTML and caches it. It validates the bundle host. The inspected helper uses the discovered
contents hash for both operation names; that is an observation requiring independent
live validation, not an assumption our contracts bake in. It retries token rejection
once and rediscovery once on persisted-query errors. Pagination rejects missing pages
and limits runaway loops. Its normalization/filtering is monitor-oriented; Consolidator
must retain unavailable slots and duplicate occurrences rather than copy those filters.

Official reads are attempted where configured; restrictions and repeated failures can
make upstream prefer Web Player. User-token requests have a temporary per-playlist
fallback cache. Our stricter policy is described in architecture.md: preserve auth,
rate-limit, network and protocol errors as distinct outcomes.

## Implementation plan and failure behavior

Keep endpoint URLs, operation specifications, bundle host allowlist, page limits,
TOTP version/material and query discovery policy in `web_player_config.py`. That module
and the network adapter are deferred; no unverified live client is shipped here.
Inject separate token and query-spec providers for fixture tests and replacement.
Use official OAuth only for destination writes. Do not download and execute remote
JavaScript or consume a third-party secret feed by default. A future secret update must
validate its format and origin, and explain how the operator refreshes it.

Expected failures: expired tokens, changed TOTP version, clock skew, unavailable Date
header, bundle layout changes, unknown hashes, GraphQL errors in HTTP 200, malformed
metadata, private/deleted/region-restricted playlists, pagination gaps and rate limits.
Raise sanitized `SpotifyWebPlayerProtocolError` on protocol mismatch, not an empty
successful list. Preserve existing imported data until a complete replacement is ready.
Validate discovered URLs and redirects against approved Spotify hosts and cap response
sizes before bundle parsing. Never include tokens or full authenticated requests in logs.

This research verifies what the reference code does; it does not establish that Spotify's
live service currently accepts the protocol. Live validation and realistic mocked fixtures
are explicit prerequisites of the reader milestone. No Spotify account was accessed.
