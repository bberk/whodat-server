"""Engine and session handling.

The engine and session factory are created lazily and cached, so importing this module never
touches a database. `get_session` is the FastAPI dependency.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine for the configured database URL."""
    return create_engine(get_settings().database_url, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the session factory bound to the process-wide engine."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and closes it when the request ends."""
    with get_session_factory()() as session:
        yield session
