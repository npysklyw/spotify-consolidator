from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata; schema changes will be managed exclusively by Alembic."""
