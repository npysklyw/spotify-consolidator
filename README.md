# Spotify Consolidator

A local-first tool for reconstructing a Spotify library from existing playlists and
public playlist links, with canonical tracks, source provenance and reviewed playlist plans.

**Current milestone: architecture and runnable foundation.** The backend health endpoint,
frontend navigation shell, playlist-ID parser, reader contracts and offline tests work.
OAuth, database tables/migrations, import, planning and writes are not implemented yet.
The UI labels these states explicitly. No Spotify credentials are needed at this stage.

Read [architecture and domain model](docs/architecture.md) and
[Web Player research](docs/spotify-web-player.md) for decisions and the next milestones.

## Local development

Requires Python 3.12+, Node 20.19+ and npm. From the repository root:

```sh
cp .env.example .env
make setup
make dev
```

In a second terminal:

```sh
make frontend
```

Open http://localhost:5173. Backend: http://127.0.0.1:8000/api/health;
OpenAPI: http://127.0.0.1:8000/docs. Frontend proxies `/api` to the backend.
Configuration reads the root `.env` even when the backend starts in its own directory.
SQLite is the local default; no schema is created or used by the foundation endpoint.

```sh
make test       # pytest + Vitest; no live Spotify calls
make lint       # Ruff, formatting check, ESLint
make typecheck  # strict mypy + TypeScript
make check      # all checks + production frontend build
```

`make migration` intentionally exits with an explanation until milestone 2 introduces
SQLAlchemy models and a reviewed initial Alembic migration. No create_all shortcut is used.

## Docker Compose

Requires Docker with Compose:

```sh
git clone <your-repository-url>
cd <repository-directory>
cp .env.example .env
docker compose up --build
```

Open http://localhost:5173. Compose includes PostgreSQL with a persistent volume, the
FastAPI backend and a built frontend served by nginx. Only loopback HTTP ports are
published. PostgreSQL is provisioned for the next persistence milestone; health currently
checks only backend liveness. The default database password is for local development.
Do not expose this unauthenticated foundation build to the internet.

Frontend dependencies are locked in package-lock.json. Backend direct dependencies are
bounded in pyproject.toml; a full reproducible Python lock is a follow-up before release.

## Sample input and secrets

`links.txt`, when present, is personal sample input and is ignored by Git. It is not read
automatically, uploaded, or embedded in application code. `.env`, local databases and
virtual environments are also ignored. Do not put Spotify tokens in frontend variables.

## Next milestone

Implement the documented persistence model and initial Alembic migration, then reader
adapters and idempotent public imports with provenance and per-playlist failure tests.
Only after those checks pass should catalogue, plans and Spotify write flows be built.
