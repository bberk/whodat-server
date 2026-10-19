"""Migration coverage for the per-season league settings table (AC-DB-06).

The table is added by revision ``0003_league_season`` on top of ``0002_initial_schema``. These
tests exercise the SQLite dialect (the local and pre-push default); CI runs the rest of the suite
against Postgres. ``alembic check`` fails if the model and the migration drift apart.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "0002_initial_schema"
NEW_REVISION = "0003_league_season"
LEAGUE_SEASON_COLUMNS = {"id", "league_id", "season", "metadata", "created_at", "updated_at"}


def _migration_config(database_url: str) -> Config:
    """Build an Alembic configuration bound to a test database URL."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _inspect_league_season(database_url: str) -> dict[str, object]:
    """Reflect league_season, disposing the temporary engine even when the table is absent."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            present = "league_season" in set(inspector.get_table_names())
            if not present:
                return {"present": False}
            return {
                "present": True,
                "columns": {column["name"] for column in inspector.get_columns("league_season")},
                "unique_keys": {
                    (constraint["name"], tuple(constraint["column_names"]))
                    for constraint in inspector.get_unique_constraints("league_season")
                },
                "foreign_keys": {
                    (foreign_key["name"], tuple(foreign_key["constrained_columns"]))
                    for foreign_key in inspector.get_foreign_keys("league_season")
                },
            }
    finally:
        engine.dispose()


def test_AC_DB_06_league_season_migration_upgrade_and_downgrade_round_trip(tmp_path: Path) -> None:
    """An empty database reaches head with league_season and round-trips through its revision."""
    database_url = f"sqlite:///{tmp_path / 'league-season.db'}"
    config = _migration_config(database_url)

    command.upgrade(config, "head")
    command.check(config)
    migrated = _inspect_league_season(database_url)
    assert migrated["present"] is True
    assert migrated["columns"] == LEAGUE_SEASON_COLUMNS
    assert migrated["unique_keys"] == {("uq_league_season_league_season", ("league_id", "season"))}
    assert migrated["foreign_keys"] == {("fk_league_season_league_id_league", ("league_id",))}

    command.downgrade(config, PREVIOUS_REVISION)
    assert _inspect_league_season(database_url)["present"] is False
    command.upgrade(config, "head")
    assert _inspect_league_season(database_url)["present"] is True


def test_league_season_revision_is_the_single_head_after_the_initial_schema() -> None:
    """Exactly one new migration adds the table, directly after the existing head."""
    config = _migration_config("sqlite://")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [NEW_REVISION]
    revision = script.get_revision(NEW_REVISION)
    assert revision.down_revision == PREVIOUS_REVISION
    assert script.get_revision(PREVIOUS_REVISION).down_revision == "0001_baseline"
