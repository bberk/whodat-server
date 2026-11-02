"""Shared test fixtures.

Database tests use one schema for the whole test session and wrap each test in an outer
transaction that is rolled back afterwards. Sessions created by the service under test are bound to
the same connection with ``join_transaction_mode="create_savepoint"``, so their commits release a
savepoint instead of committing the test transaction. The result is a clean database for every
test without creating or dropping the schema per test, on SQLite locally and on Postgres when
``REPOSITORY_TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base


def _configure_sqlite_savepoints(engine: Engine) -> None:
    """Make pysqlite honor BEGIN/SAVEPOINT so the outer test transaction can roll back.

    The driver otherwise commits at the end of a savepoint release. This is SQLAlchemy's
    documented recipe for transactional tests and savepoints on SQLite.
    """

    @event.listens_for(engine, "connect")
    def _sqlite_connect(dbapi_connection: object, _record: object) -> None:
        dbapi_connection.isolation_level = None  # type: ignore[attr-defined]

    @event.listens_for(engine, "begin")
    def _sqlite_begin(connection: object) -> None:
        connection.exec_driver_sql("BEGIN")  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Create one schema for the test session, on SQLite or Postgres."""
    url = os.environ.get("REPOSITORY_TEST_DATABASE_URL", "sqlite://")
    if url.startswith("sqlite"):
        # One in-memory database shared by every session in this process.
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _configure_sqlite_savepoints(engine)
    else:
        engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Yield a session factory bound to one outer transaction, rolled back after the test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield factory
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session inside the shared outer transaction."""
    with db_session_factory() as session:
        yield session
