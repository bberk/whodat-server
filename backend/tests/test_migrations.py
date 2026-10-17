from pathlib import Path

from alembic import command
from alembic.config import Config

from app import cli, config, db, domain, providers, services  # noqa: F401
from app.api import main as api_main  # noqa: F401
from app.api import routes_health  # noqa: F401
from app.db import base, session

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_AC_DB_06_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    """A migration from an empty database to head succeeds and downgrades back to base."""
    cfg = _config(f"sqlite:///{tmp_path / 'migrate.db'}")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")


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
