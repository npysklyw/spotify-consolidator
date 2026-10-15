# Spotify Consolidator architecture

## Status and delivery boundary

Milestone 1 is a runnable foundation: FastAPI liveness endpoint, React navigation shell,
configuration, reader contracts, playlist parsing, and offline tests. This document
specifies the subsequent implementation; it does not claim those features exist.
Database tables, Alembic migrations, OAuth, network readers, imports, plans and writes
are deliberately deferred to separately verified milestones. No credentials are
required to run this build. The starting directory was empty.

## Product and boundaries

A single-user, local-first workspace reconstructs a canonical catalogue from selected
existing-account playlists and arbitrary public playlist links. Empty destination
accounts are normal. Existing playlists stay untouched unless selected as explicit
write targets later. Saved tracks are outside the initial source workflow.

React + TypeScript + TanStack Query → FastAPI request schemas → application services
→ repositories / SQLAlchemy 2 → SQLite locally or PostgreSQL in deployment.
Services call Spotify reader/writer protocols; only `app/integrations/spotify` performs
Spotify HTTP requests using injected httpx clients. Domain code never parses Spotify JSON.
Use synchronous SQLAlchemy transactions in short worker-thread operations, outside async
network waits. Avoid sharing sessions across concurrent imports. No job broker is needed.

Frontend requests use same-origin `/api`: Vite proxies locally; nginx proxies in Compose.
Bind development servers to loopback where possible and expose Compose ports only on
loopback. Production internet hosting requires a separate authentication/deployment review.
Health is process liveness, not a claim of database or Spotify connectivity.

## Domain and persistence design

All local primary keys are integer IDs. Timestamps are UTC. External Spotify IDs are
strings with unique constraints; unknown metadata is nullable rather than fabricated.

| Entity | Fields and constraints |
| --- | --- |
| SpotifyAccount | id; unique spotify_user_id; display_name; created_at; updated_at |
| Playlist | id; unique spotify_playlist_id; spotify_owner_id; name; description; nullable public; collaborative; snapshot_id; source_type (destination_account/public_url/generated); destination_managed; last_synced_at; created_at; updated_at |
| Track | id; unique spotify_track_id; spotify_uri; name; nullable album_name, duration_ms, explicit, isrc; created_at; updated_at |
| Artist | id; unique spotify_artist_id; name |
| TrackArtist | track_id + artist_id composite primary key; artist ordering |
| SourceOccurrence | id; playlist_id; nullable track_id; position; added_at; added_by; unavailable_reason; unique (playlist_id, position) |
| PlaylistPlan | id; name; destination_account_id; revision; created_at; updated_at |
| PlannedPlaylist | id; plan_id; name; description; public; nullable target_playlist_id; nullable applied_spotify_playlist_id; rules JSON; updated_at |
| PlannedPlaylistTrack | planned_playlist_id + track_id composite primary key; position; unique (planned_playlist_id, position) |
| ImportRun / ImportItem | run status and counters; per-item normalized ID, source kind, status, sanitized failure and skip counts |
| ApplyRun / ApplyItem | reviewed plan revision and digest; per-playlist remote ID, phase, progress, snapshot and error |

SourceOccurrence preserves repeated tracks within one playlist and across playlists.
Unavailable tracks, local files, and episodes retain their original slot and a reason;
they do not produce invented track IDs. Missing artists must not be merged by name.
Canonical identity is Spotify track ID; ISRC is metadata, not a uniqueness constraint.
`DeduplicationService` owns this policy for future alternative recording identities.

`source_type` records discovery origin, not ownership or write permission. If the same
playlist is imported via a link and discovered in the account, its external ID resolves
to the same row. Ownership is independently checked against the connected account.
Add explicit source-selection state when discovery is persisted; discovered-but-unselected
playlists must not silently enter the library. An account switch cannot retarget old plans.

## Ingestion and statistics

Normalize each input independently. Deduplicate equivalent requested playlist IDs while
reporting input count and unique requests separately. Short base62 IDs are accepted to
support brief examples; actual existence is determined remotely. Never fetch user URLs
directly: extract IDs and construct allowlisted Spotify endpoints.

Fetch complete metadata and every page before starting a transaction. Bound page counts,
timeouts and concurrency; reject malformed pages and unexpected early exhaustion.
Where revisions are available, recheck after pagination and retry a bounded number of
times if the playlist changed. Do not replace a good import with an incomplete read.

One transaction per playlist upserts artists, tracks and playlist metadata, replaces that
playlist's occurrences, and records success. Roll back that playlist on failure and
continue the other inputs. Unique constraints and a single active import worker prevent
racing replacements. Re-importing refreshes current state, not append-only occurrences.
Revision metadata and the import run leave room for snapshot history without promising it.
A future history table can reference immutable import versions.

Durable run records with an in-process worker and polling provide progress for dozens of
playlists. Restart marks interrupted work retryable. Implement resumability before claiming
background jobs are durable. SQLite writes are serialized. No Redis/Celery required.

Library stats count selected, successfully imported source playlists, raw slots, readable
track occurrences, unique referenced tracks, unavailable slots and unique referenced artists.
Duplicate occurrences = readable occurrences minus unique tracks. Distinct source count
uses COUNT(DISTINCT playlist_id), not repeated slots. With no unavailable entries this
matches the requested playlist_entries − unique_tracks formula. Orphaned tracks retained
for plans/history do not inflate source-library stats.

## Spotify transports and authentication

`PlaylistReader` returns validated metadata and ordered occurrence DTOs, including missing
slots. This deliberately improves the suggested list-of-tracks interface so provenance
and source positions survive normalization. `OfficialSpotifyClient`,
`SpotifyWebPlayerClient`, and `CompositeSpotifyReader` will implement this contract.

Prefer official destination OAuth reads. Fall back for public-playlist access restrictions
(403/404 or explicitly missing restricted content), with a short per-playlist decision
cache. 404 alone cannot prove restriction: if both readers fail report unavailable.
Refresh an expired token once; honor Retry-After on 429; use bounded jittered backoff for
transient network/5xx failures. Do not treat every exception as permission to fall back,
or use the alternate transport to evade rate limits. Restart full playlist retrieval on
transport switch, avoiding mixed revisions across pages.

Destination OAuth uses authorization code + PKCE and validated, expiring, single-use state.
Tokens stay server-side; refresh under a lock. Store persisted refresh tokens encrypted
with a local key outside the database, or use the OS keychain. Never send tokens in URLs,
frontend state, error responses or logs. Same-origin session cookies and CSRF/origin checks
must precede mutation endpoints. This skeleton contains no authentication endpoints.
Web Player access uses a separate provider/cache/configuration and never borrows destination
tokens. See [protocol research](spotify-web-player.md).

## Local plans, rules, review, and apply

Rules are backend-validated discriminated schemas: source is one/any playlist, artist ID,
and minimum distinct source count. Rule evaluation materializes explicit membership;
manual edits operate on the resulting set. Re-evaluation is explicit, so later imports
cannot silently alter a reviewed plan. An optional configurable “everything” rule selects
all current canonical library tracks. Tracks can belong to multiple planned playlists.

Preview compares ordered desired URI lists against live destination state and reports
CREATE / UPDATE / UNCHANGED, additions, removals, and reorder-only changes. It includes a
plan revision/digest, destination account and target snapshots. Apply requires explicit
confirmation of that exact preview; stale local revisions or remote snapshots require
another review. No deletion of Spotify playlists is supported.

`SpotifyWriter` exposes create_playlist, add_tracks and replace_playlist_tracks. Use the
official API, paginate reads and chunk writes at the supported limit verified when
implemented. Preserve desired order, deduplicate destination membership, and record each
confirmed remote ID before adding tracks. A timed-out create is ambiguous: do not blindly
retry and create duplicate playlists. Reconcile or request intervention. Replacement
batches can leave partial remote state; persist progress and re-read before resuming.
Return per-playlist results and partial failures. No global remote transaction is promised.

## API roadmap

Implemented: `GET /api/health`, automatic OpenAPI at `/docs`.

Next: Spotify OAuth start/callback, `GET /api/spotify/me`, account playlist discovery;
`POST /api/import/public-playlists`, `POST /api/import/account-playlists`, import status;
`GET /api/library` with pagination/filter/sort and `/api/library/stats`.
Then plan CRUD, planned playlist creation/membership/rule evaluation, plan diff and apply.
All requests and responses use explicit Pydantic schemas. Do not expose pretend endpoints
returning empty successful results for unimplemented integrations.

## Milestones and acceptance gates

1. **Foundation (this change):** docs, runnable shell, contracts, parser, offline checks.
2. **Persistence:** complete SQLAlchemy models, explicit initial Alembic revision; upgrade
   and downgrade tests on SQLite and PostgreSQL; foreign-key enforcement and uniqueness.
3. **Readers + imports:** mocked official/Web Player fixtures, token/hash refresh,
   full pagination, duplicate provenance, rerun idempotency, 9/10 partial success,
   unavailable slots, changed snapshots, and safe persistence on failed refresh.
4. **Destination OAuth + catalogue UI:** empty/established account discovery, selected
   sources, progress, filters, sorting, provenance and statistics.
5. **Local organization:** plan membership, rules and configurable full-library playlist;
   tests for distinct source counts, add/remove, and order-aware diffs.
6. **Preview + official writes:** preview binding, batch limits, partial/ambiguous writes,
   explicit apply and recovery. Live tests are opt-in with a disposable account.

After each milestone run pytest, Ruff (including formatting), strict mypy, frontend lint,
tests and TypeScript/build checks. Normal tests must never depend on Spotify or credentials.
