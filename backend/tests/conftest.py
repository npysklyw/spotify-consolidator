import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from app.db.session import make_engine, session_factory


def migration_config(url: str) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if postgres_url:
        # Every test owns an isolated schema; never truncate an existing application schema.
        schema = "consolidator_test_" + uuid4().hex
        admin = make_engine(postgres_url)
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        url = (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    else:
        url = f"sqlite:///{tmp_path / 'test.db'}"
        admin = None
    engine = make_engine(url)
    try:
        command.upgrade(migration_config(url), "head")
        command.check(migration_config(url))
        yield session_factory(engine)
        command.downgrade(migration_config(url), "base")
        command.upgrade(migration_config(url), "head")
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            admin.dispose()
