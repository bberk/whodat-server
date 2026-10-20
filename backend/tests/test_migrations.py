"""Migration coverage for the schema chain (AC-DB-06).

One head round-trip runs on SQLite; a ``postgres``-marked variant runs the same round trip against
a throwaway database in the configured Postgres instance (CI and worktree-local Postgres).
``alembic check`` fails if the models and the migrations drift apart. The exact shape of a
historical revision is guaranteed by that revision's own migration file, so it is not re-asserted
here; only the head DDL and the single linear chain are checked.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from app import cli, config, db, domain, providers, services  # noqa: F401
from app.api import main as api_main  # noqa: F401
from app.api import routes_health  # noqa: F401
from app.config import get_settings
from app.db import base, session

BACKEND_DIR = Path(__file__).resolve().parents[1]
APPLICATION_TABLES = {
    "league",
    "league_season",
    "owner",
    "team",
    "matchup",
    "score",
    "app_user",
    "invite",
    "user_league",
}
# Columns whose presence in the migrated head DDL prove the migrations ran (migrated-DDL check).
HEAD_COLUMNS = {
    "score": {"points", "victory_points", "vp_h2h", "vp_top_half", "vp_high", "vp_low"},
    "league_season": {"league_id", "season", "metadata"},
    "app_user": {"email", "password_hash", "role"},
    "invite": {"league_id", "code_hash", "role", "expires_at"},
    "user_league": {
        "user_id",
        "league_id",
        "owner_id",
        "espn_s2_encrypted",
        "espn_swid_encrypted",
    },
}


def _config(database_url: str) -> Config:
    """Build an Alembic configuration bound to a test database URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _table_names(database_url: str) -> set[str]:
    """Inspect a database while disposing the temporary engine afterward."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def _column_names(database_url: str, table_name: str) -> set[str]:
    """Return the reflected columns for one migrated table."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return {column["name"] for column in inspect(connection).get_columns(table_name)}
    finally:
        engine.dispose()


def _column_is_nullable(database_url: str, table_name: str, column_name: str) -> bool:
    """Return the reflected nullability of one column in a migrated database."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            columns = inspect(connection).get_columns(table_name)
    finally:
        engine.dispose()
    return next(column["nullable"] for column in columns if column["name"] == column_name)


def _assert_invite_league_keeps_its_fk_and_index(database_url: str) -> None:
    """The nullable league column keeps the foreign key and index that 0004 created."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            foreign_keys = inspector.get_foreign_keys("invite")
            indexes = inspector.get_indexes("invite")
    finally:
        engine.dispose()
    assert any(
        foreign_key["name"] == "fk_invite_league_id_league"
        and foreign_key["constrained_columns"] == ["league_id"]
        for foreign_key in foreign_keys
    )
    assert any(index["name"] == "ix_invite_league_id" for index in indexes)


def _assert_nullable_invite_league_round_trip(database_url: str) -> None:
    """0005 makes league_id nullable and 0004-era downgrades restore NOT NULL."""
    config = _config(database_url)

    command.upgrade(config, "0005_invite_optional_league")
    assert _column_is_nullable(database_url, "invite", "league_id") is True
    _assert_invite_league_keeps_its_fk_and_index(database_url)

    command.downgrade(config, "0004_auth_memberships")
    assert _column_is_nullable(database_url, "invite", "league_id") is False
    _assert_invite_league_keeps_its_fk_and_index(database_url)

    command.upgrade(config, "0005_invite_optional_league")
    assert _column_is_nullable(database_url, "invite", "league_id") is True


def _assert_migrated_ddl(database_url: str) -> None:
    """Assert the migrated head DDL has the application tables and their required columns."""
    assert _table_names(database_url) >= APPLICATION_TABLES
    for table_name, expected in HEAD_COLUMNS.items():
        assert _column_names(database_url, table_name) >= expected


def _round_trip(database_url: str) -> None:
    """Upgrade empty to head, check for drift, then downgrade to base and re-upgrade."""
    config = _config(database_url)

    command.upgrade(config, "head")
    command.check(config)
    _assert_migrated_ddl(database_url)

    command.downgrade(config, "base")
    assert not APPLICATION_TABLES & _table_names(database_url)

    command.upgrade(config, "head")
    command.check(config)
    _assert_migrated_ddl(database_url)


def test_AC_DB_06_migration_round_trips_on_sqlite(tmp_path: Path) -> None:
    """An empty SQLite database reaches head, checks cleanly, and round-trips to base and back."""
    _round_trip(f"sqlite:///{tmp_path / 'migrate.db'}")


def test_invite_league_nullability_round_trips_on_sqlite(tmp_path: Path) -> None:
    """0005 makes invite.league_id nullable and its downgrade restores NOT NULL on SQLite."""
    _assert_nullable_invite_league_round_trip(f"sqlite:///{tmp_path / 'invite-optional.db'}")


def test_invite_league_downgrade_rejects_rows_without_a_league(tmp_path: Path) -> None:
    """The downgrade fails cleanly while a null-league invite would violate NOT NULL."""
    database_url = f"sqlite:///{tmp_path / 'invite-null-downgrade.db'}"
    command.upgrade(_config(database_url), "0005_invite_optional_league")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO invite "
                    "(league_id, code_hash, role, expires_at, created_at, updated_at) "
                    "VALUES (NULL, 'admin-no-league', 'admin', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="invite row\\(s\\) have no league_id"):
        command.downgrade(_config(database_url), "0004_auth_memberships")
    assert _column_is_nullable(database_url, "invite", "league_id") is True


def test_migration_chain_is_a_single_linear_head() -> None:
    """The chain has exactly one head and one parent per revision, so it never branches."""
    script = ScriptDirectory.from_config(_config("sqlite://"))

    assert len(script.get_heads()) == 1
    revisions = list(script.walk_revisions(base="base", head="heads"))
    down_revisions = [revision.down_revision for revision in revisions]
    # A merge revision records a tuple of parents; this chain must have none.
    assert all(
        down_revision is None or isinstance(down_revision, str) for down_revision in down_revisions
    )
    assert down_revisions.count(None) == 1


def _configured_postgres_admin_url() -> URL | None:
    """Return the configured Postgres URL, or None when the configured database is SQLite."""
    configured = make_url(get_settings().database_url)
    if configured.get_backend_name() != "postgresql":
        return None
    return configured


@contextmanager
def _temporary_postgres_database(admin_url: URL) -> Iterator[str]:
    """Create a throwaway database for one migration test and drop it afterwards."""
    database_name = f"whodat_migration_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        yield admin_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.mark.postgres
def test_AC_DB_06_migration_round_trips_on_postgres() -> None:
    """The same head round trip holds on a throwaway database in the configured Postgres."""
    admin_url = _configured_postgres_admin_url()
    if admin_url is None:
        pytest.skip("configured DATABASE_URL is not Postgres")

    with _temporary_postgres_database(admin_url) as database_url:
        _round_trip(database_url)


@pytest.mark.postgres
def test_invite_league_nullability_round_trips_on_postgres() -> None:
    """0005's upgrade and downgrade behave the same on Postgres as on SQLite."""
    admin_url = _configured_postgres_admin_url()
    if admin_url is None:
        pytest.skip("configured DATABASE_URL is not Postgres")

    with _temporary_postgres_database(admin_url) as database_url:
        _assert_nullable_invite_league_round_trip(database_url)


def test_import_boundary_modules_load() -> None:
    """Every package in the layout imports without side effects."""
    assert api_main.create_app is not None
    assert routes_health.router is not None
    assert base.Base is not None
    assert session.get_session is not None
    assert config.get_settings is not None
    assert cli.main is not None
    assert db is not None
    assert domain is not None
    assert providers is not None
    assert services is not None
