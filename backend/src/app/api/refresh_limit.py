"""Application-wide refresh rate limiter wiring.

The limiter itself lives in :mod:`app.services.league_service` so the service can enforce it
without depending on the HTTP layer. This module owns the process-wide instance and the FastAPI
dependency used by the league routes; tests override :func:`get_refresh_limiter` (or inject their
own limiter into a service) with a fake clock.
"""

from __future__ import annotations

from app.services.league_service import RefreshRateLimiter

_refresh_limiter = RefreshRateLimiter()


def get_refresh_limiter() -> RefreshRateLimiter:
    """Return the application-wide league-refresh rate limiter."""
    return _refresh_limiter
