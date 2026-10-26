"""Application-wide refresh rate limiter wiring.

The limiters themselves live in :mod:`app.services.league_service` so the service can enforce them
without depending on the HTTP layer. This module owns the process-wide instances and the FastAPI
dependencies used by the league routes: one bucket for the league-wide refresh and a separate,
more permissive bucket for the admin per-season refresh. Tests override the getters (or inject
their own limiters into a service) with a fake clock.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.league_service import RefreshRateLimiter

_settings = get_settings()

_refresh_limiter = RefreshRateLimiter(
    league_interval_seconds=_settings.refresh_league_interval_seconds,
    user_limit=_settings.refresh_user_limit,
    user_window_seconds=_settings.refresh_user_window_seconds,
)

_season_refresh_limiter = RefreshRateLimiter(
    league_interval_seconds=_settings.season_refresh_league_interval_seconds,
    user_limit=_settings.season_refresh_user_limit,
    user_window_seconds=_settings.season_refresh_user_window_seconds,
)


def get_refresh_limiter() -> RefreshRateLimiter:
    """Return the application-wide league-refresh rate limiter."""
    return _refresh_limiter


def get_season_refresh_limiter() -> RefreshRateLimiter:
    """Return the application-wide per-season refresh rate limiter."""
    return _season_refresh_limiter
