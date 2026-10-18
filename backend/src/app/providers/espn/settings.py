"""Provider-local ESPN settings for credentials and configuration.

These settings are scoped to the ESPN provider and are NOT part of the general
app.config.Settings. This keeps ESPN-specific credentials isolated from the
rest of the application (ARCHITECTURE.md section 10, AGENTS.md working rules).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# settings.py -> espn -> providers -> app -> src -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]


class ESPNSettings(BaseSettings):
    """ESPN-specific settings, read from environment variables.

    ESPN credentials (espn_s2, swid) are required for private leagues.
    These are read ONLY by the ESPN provider and must never appear in logs,
    error messages, or API responses (AC-DB-08).

    The adapter reads `ESPN_S2` and `ESPN_SWID` (matching `.env.example`).
    Values come from the real environment first, then fall back to the
    repo-root `.env` file.
    """

    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    espn_s2: str = ""
    espn_swid: str = ""

    def has_credentials(self) -> bool:
        """Return True when both ESPN auth cookies are configured."""
        return bool(self.espn_s2 and self.espn_swid)


@lru_cache
def get_espn_settings() -> ESPNSettings:
    """Return the process-wide ESPN settings, read once and cached."""
    return ESPNSettings()
