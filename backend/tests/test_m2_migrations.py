from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_TABLES = {"league", "owner", "team", "matchup", "score", "app_user"}


def _migration_config(database_url: str) -> Config:
    """Build an Alembic configuration bound to a test database URL."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


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


def test_AC_DB_06_empty_upgrade_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    """A fresh SQLite database reaches head and can round-trip to base and back."""
    database_url = f"sqlite:///{tmp_path / 'm2-schema.db'}"
    config = _migration_config(database_url)

    command.upgrade(config, "head")
    command.check(config)
    assert _table_names(database_url) >= SCHEMA_TABLES
    assert _column_names(database_url, "score") >= {
        "victory_points",
        "vp_h2h",
        "vp_top_half",
        "vp_high",
        "vp_low",
    }

    command.downgrade(config, "base")
    assert not SCHEMA_TABLES & _table_names(database_url)

    command.upgrade(config, "head")
    assert _table_names(database_url) >= SCHEMA_TABLES
