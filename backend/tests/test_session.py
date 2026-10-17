from pathlib import Path

from sqlalchemy.orm import Session

from app import config
from app.db import session as session_module


def test_get_session_yields_a_session(tmp_path: Path, monkeypatch) -> None:
    """get_session yields a live Session bound to the configured database."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sessions.db'}")
    config.get_settings.cache_clear()
    session_module.get_engine.cache_clear()
    session_module.get_session_factory.cache_clear()
    try:
        session = next(session_module.get_session())
        try:
            assert isinstance(session, Session)
        finally:
            session.close()
    finally:
        # Do not leak the temporary database URL into other tests.
        config.get_settings.cache_clear()
        session_module.get_engine.cache_clear()
        session_module.get_session_factory.cache_clear()
