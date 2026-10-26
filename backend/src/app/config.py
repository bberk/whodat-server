"""Application settings, read from the environment (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> app -> src -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The placeholder shipped in `.env.example`. It is safe for local development and tests only.
DEFAULT_SECRET_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    """Environment-driven settings.

    Values come from real environment variables first; a `.env` file at the repository root is
    used as a fallback for local development. Unknown variables are ignored so a shared `.env`
    can carry frontend-only variables without breaking the backend.
    """

    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = DEFAULT_SECRET_KEY
    env: str = "local"
    cors_origins: str = "http://localhost:5173"
    league_credentials_key: str | None = None

    # League-wide refresh (the member refresh route): one per league every five minutes and three
    # per user per hour by default. These remain deliberately conservative.
    refresh_league_interval_seconds: float = Field(default=300.0, ge=0)
    refresh_user_limit: int = Field(default=3, ge=1)
    refresh_user_window_seconds: float = Field(default=3600.0, gt=0)

    # Admin per-season refresh has its own bucket. It allows consecutive season refreshes (the
    # league interval is zero by default) while still capping one administrator's volume.
    season_refresh_league_interval_seconds: float = Field(default=0.0, ge=0)
    season_refresh_user_limit: int = Field(default=60, ge=1)
    season_refresh_user_window_seconds: float = Field(default=3600.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once and cached."""
    return Settings()
