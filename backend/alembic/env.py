from typing import Any

from sqlalchemy.types import TypeEngine

from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import database_url, make_engine
from app.db.types import UTCDateTime
from app.models import Artist, Playlist, PlaylistTrack, Track, TrackArtist  # noqa: F401


def render_item(kind: str, item: TypeEngine[Any], autogen_context: Any) -> str | bool:
    if kind == "type" and isinstance(item, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


config = context.config
url = config.attributes.get("database_url") or get_settings().database_url

if context.is_offline_mode():
    context.configure(
        url=database_url(url),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=engine.dialect.name == "sqlite",
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
