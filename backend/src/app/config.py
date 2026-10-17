"""Application settings, read from the environment (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> app -> src -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Environment-driven settings.

    Values come from real environment variables first; a `.env` file at the repository root is
    used as a fallback for local development. Unknown variables are ignored so a shared `.env`
    can carry frontend-only variables without breaking the backend.
    """

    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-insecure-change-me"
    env: str = "local"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once and cached."""
    return Settings()
