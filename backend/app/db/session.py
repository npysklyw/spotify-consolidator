from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

# Resolve relative SQLite paths identically for CLI, Alembic, uvicorn and tests.
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def database_url(value: str) -> str:
    url = make_url(value)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        assert url.database is not None
        path = Path(url.database)
        if not path.is_absolute():
            url = url.set(database=str(BACKEND_ROOT / path))
    return url.render_as_string(hide_password=False)


def make_engine(url: str) -> Engine:
    options: dict[str, Any] = {}
    if make_url(url).get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url(url), **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection: Any, _: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
