"""Migration coverage for invite-only accounts and league memberships.

Revision ``0004_auth_memberships`` creates ``invite`` and ``user_league`` and rewrites ``app_user``
in a batch so SQLite can drop ``owner_id``. These tests round-trip upgrade, downgrade, and upgrade
on SQLite by default, and on a worktree-local Postgres when ``AUTH_MIGRATION_POSTGRES_URL`` is set
(for example from ``scripts/dev-postgres.sh url``).
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "0003_league_season"
NEW_REVISION = "0004_auth_memberships"
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
INVITE_COLUMNS = {"id", "league_id", "code_hash", "role", "expires_at", "created_at", "updated_at"}
USER_LEAGUE_COLUMNS = {
    "id",
    "user_id",
    "league_id",
    "owner_id",
    "espn_s2_encrypted",
    "espn_swid_encrypted",
    "created_at",
    "updated_at",
}


def _migration_config(database_url: str) -> Config:
    """Build an Alembic configuration bound to a test database URL."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_shape(inspector: object, table_name: str) -> dict[str, object]:
    """Return the reflected columns, constraints, and indexes for one table."""
    return {
        "columns": {
            column["name"]: column
            for column in inspector.get_columns(table_name)  # type: ignore[attr-defined]
        },
        "unique_constraints": {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(table_name)  # type: ignore[attr-defined]
        },
        "foreign_keys": {
            (foreign_key["name"], tuple(foreign_key["constrained_columns"]))
            for foreign_key in inspector.get_foreign_keys(table_name)  # type: ignore[attr-defined]
        },
        "indexes": {
            (index["name"], tuple(index["column_names"]))
            for index in inspector.get_indexes(table_name)  # type: ignore[attr-defined]
        },
    }


def _inspect_database(database_url: str) -> dict[str, object]:
    """Reflect the application schema, disposing the temporary engine afterward."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            return {
                "tables": tables,
                "app_user": _table_shape(inspector, "app_user") if "app_user" in tables else None,
                "invite": _table_shape(inspector, "invite") if "invite" in tables else None,
                "user_league": _table_shape(inspector, "user_league")
                if "user_league" in tables
                else None,
            }
    finally:
        engine.dispose()


def _assert_head_schema(database_url: str) -> None:
    """Assert the upgraded schema matches the auth/membership contract."""
    inspected = _inspect_database(database_url)
    assert inspected["tables"] >= APPLICATION_TABLES

    app_user = inspected["app_user"]
    assert app_user is not None
    app_user_columns = app_user["columns"]
    assert "role" in app_user_columns
    assert "owner_id" not in app_user_columns
    assert app_user_columns["role"]["nullable"] is False
    assert "member" in str(app_user_columns["role"]["default"])
    assert app_user["foreign_keys"] == set()

    invite = inspected["invite"]
    assert invite is not None
    assert set(invite["columns"]) == INVITE_COLUMNS
    assert invite["columns"]["code_hash"]["nullable"] is False
    assert invite["columns"]["expires_at"]["nullable"] is False
    assert invite["columns"]["role"]["nullable"] is False
    assert "member" in str(invite["columns"]["role"]["default"])
    assert invite["unique_constraints"] == {("uq_invite_code_hash", ("code_hash",))}
    assert invite["foreign_keys"] == {("fk_invite_league_id_league", ("league_id",))}
    assert ("ix_invite_league_id", ("league_id",)) in invite["indexes"]

    membership = inspected["user_league"]
    assert membership is not None
    assert set(membership["columns"]) == USER_LEAGUE_COLUMNS
    assert membership["columns"]["owner_id"]["nullable"] is True
    assert membership["columns"]["espn_s2_encrypted"]["nullable"] is True
    assert membership["columns"]["espn_swid_encrypted"]["nullable"] is True
    assert membership["unique_constraints"] == {
        ("uq_user_league_user_id_league_id", ("user_id", "league_id"))
    }
    assert membership["foreign_keys"] == {
        ("fk_user_league_user_id_app_user", ("user_id",)),
        ("fk_user_league_league_id_league", ("league_id",)),
        ("fk_user_league_owner_id_owner", ("owner_id",)),
    }
    assert ("ix_user_league_league_id", ("league_id",)) in membership["indexes"]


def _assert_previous_schema(database_url: str) -> None:
    """Assert the downgrade to 0003 removes the new tables and restores owner_id."""
    inspected = _inspect_database(database_url)
    assert "invite" not in inspected["tables"]
    assert "user_league" not in inspected["tables"]

    app_user = inspected["app_user"]
    assert app_user is not None
    assert "role" not in app_user["columns"]
    assert app_user["columns"]["owner_id"]["nullable"] is True
    assert app_user["foreign_keys"] == {("fk_app_user_owner_id_owner", ("owner_id",))}


def _round_trip(database_url: str) -> None:
    """Upgrade to head, downgrade to previous and base, then upgrade to head again."""
    config = _migration_config(database_url)

    command.upgrade(config, "head")
    command.check(config)
    _assert_head_schema(database_url)

    command.downgrade(config, PREVIOUS_REVISION)
    _assert_previous_schema(database_url)

    command.downgrade(config, "base")
    assert not APPLICATION_TABLES & set(_inspect_database(database_url)["tables"])

    command.upgrade(config, "head")
    command.check(config)
    _assert_head_schema(database_url)


def test_AC_DB_06_auth_migration_round_trips_on_sqlite(tmp_path: Path) -> None:
    """SQLite batch-recreates app_user so drop-column and downgrade both work."""
    _round_trip(f"sqlite:///{tmp_path / 'auth-memberships.db'}")


def test_auth_migration_is_the_single_head_after_league_season() -> None:
    """Exactly one new revision follows the previous head and nothing else branches."""
    config = _migration_config("sqlite://")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [NEW_REVISION]
    revision = script.get_revision(NEW_REVISION)
    assert revision.down_revision == PREVIOUS_REVISION
    assert script.get_revision(PREVIOUS_REVISION).down_revision == "0002_initial_schema"


@pytest.mark.skipif(
    not os.environ.get("AUTH_MIGRATION_POSTGRES_URL"),
    reason="set AUTH_MIGRATION_POSTGRES_URL to a worktree-local Postgres URL",
)
def test_AC_DB_06_auth_migration_round_trips_on_postgres() -> None:
    """The same round trip holds on a throwaway database in worktree-local Postgres."""
    configured_url = os.environ["AUTH_MIGRATION_POSTGRES_URL"]
    admin_url = make_url(configured_url)
    database_name = f"whodat_auth_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        database_url = admin_url.set(database=database_name).render_as_string(hide_password=False)
        _round_trip(database_url)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()
