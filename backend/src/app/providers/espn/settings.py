"""Provider-local ESPN settings for credentials and configuration.

These settings are scoped to the ESPN provider and are NOT part of the general
app.config.Settings. This keeps ESPN-specific credentials isolated from the
rest of the application (ARCHITECTURE.md section 10, AGENTS.md working rules).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# settings.py -> espn -> providers -> app -> src -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]


def _normalize_credential(value: str) -> str:
    """Normalize a credential value by stripping whitespace and outer quotes.

    This handles common .env formatting issues:
    - Leading/trailing whitespace (preserved by Pydantic)
    - Matching outer quote pairs (defensive, in case Pydantic behavior changes)

    Args:
        value: The raw credential string from environment/.env

    Returns:
        Normalized credential with whitespace and one matching outer quote pair removed
    """
    if not value:
        return value

    # Strip whitespace first
    result = value.strip()

    # Strip one matching pair of outer quotes if present
    if len(result) >= 2 and (
        (result.startswith('"') and result.endswith('"'))
        or (result.startswith("'") and result.endswith("'"))
    ):
        result = result[1:-1]

    return result


class ESPNSettings(BaseSettings):
    """ESPN-specific settings, read from environment variables.

    ESPN credentials (espn_s2, swid) are required for private leagues.
    These are read ONLY by the ESPN provider and must never appear in logs,
    error messages, or API responses (AC-DB-08).

    The adapter reads `ESPN_S2` and `ESPN_SWID` (matching `.env.example`).
    Values come from the real environment first, then fall back to the
    repo-root `.env` file. Credentials are automatically normalized to
    strip whitespace and matching outer quotes.
    """

    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    espn_s2: str = ""
    espn_swid: str = ""

    @model_validator(mode="after")
    def normalize_credentials(self) -> ESPNSettings:
        """Normalize credentials by stripping whitespace and outer quotes."""
        self.espn_s2 = _normalize_credential(self.espn_s2)
        self.espn_swid = _normalize_credential(self.espn_swid)
        return self

    def has_credentials(self) -> bool:
        """Return True when both ESPN auth cookies are configured."""
        return bool(self.espn_s2 and self.espn_swid)


@lru_cache
def get_espn_settings() -> ESPNSettings:
    """Return the process-wide ESPN settings, read once and cached."""
    return ESPNSettings()
