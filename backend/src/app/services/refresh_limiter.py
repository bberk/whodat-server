"""Thread-safe refresh rate limiter for league and season syncs."""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

#: A league-wide refresh is allowed once per league in this interval.
DEFAULT_LEAGUE_REFRESH_INTERVAL_SECONDS = 5 * 60.0

#: A user may trigger this many refreshes in the rolling window below.
DEFAULT_USER_REFRESH_LIMIT = 3

#: Rolling window for the per-user refresh limit.
DEFAULT_USER_REFRESH_WINDOW_SECONDS = 60 * 60.0

#: Admin per-season refresh allows consecutive seasons; the default has no per-league interval.
DEFAULT_SEASON_REFRESH_INTERVAL_SECONDS = 0.0

#: A season refresh is allowed this many times per user in the rolling window below.
DEFAULT_SEASON_REFRESH_USER_LIMIT = 60

#: Rolling window for the per-season refresh user limit.
DEFAULT_SEASON_REFRESH_USER_WINDOW_SECONDS = 60 * 60.0


@dataclass(frozen=True)
class RefreshRateLimitDecision:
    """Outcome of one league-refresh rate-limit check."""

    allowed: bool
    retry_after: int


class RefreshRateLimiter:
    """A thread-safe refresh limiter with independent per-league and per-user limits.

    The defaults allow one refresh per league every five minutes and three refreshes per user per
    rolling hour. The clock is injectable (seconds, monotonically non-decreasing in tests) so the
    behaviour is deterministic. A denied attempt does not consume quota; an allowed attempt is
    recorded before the provider call, so a failed sync still counts.

    State is process-local, like the auth limiter: a multi-worker deployment needs a shared store.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        league_interval_seconds: float = DEFAULT_LEAGUE_REFRESH_INTERVAL_SECONDS,
        user_limit: int = DEFAULT_USER_REFRESH_LIMIT,
        user_window_seconds: float = DEFAULT_USER_REFRESH_WINDOW_SECONDS,
    ) -> None:
        """Configure the limits and clock; non-negative intervals and a positive limit are valid."""
        if league_interval_seconds < 0:
            raise ValueError("league_interval_seconds must not be negative")
        if user_limit < 1:
            raise ValueError("user_limit must be at least 1")
        if user_window_seconds <= 0:
            raise ValueError("user_window_seconds must be positive")
        self._clock = clock
        self._league_interval_seconds = float(league_interval_seconds)
        self._user_limit = user_limit
        self._user_window_seconds = float(user_window_seconds)
        self._last_league_refresh: dict[int, float] = {}
        self._user_attempts: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, *, league_id: int, user_id: int) -> RefreshRateLimitDecision:
        """Record one allowed refresh or report how long the caller must wait.

        Both limits are evaluated before either counter changes, so a denial by one limit does not
        consume the other. ``retry_after`` is the largest whole-second wait implied by the two
        limits (at least one when denied).
        """
        now = float(self._clock())
        with self._lock:
            league_retry = self._league_retry(league_id, now)
            attempts = [
                attempt
                for attempt in self._user_attempts.get(user_id, [])
                if now - attempt < self._user_window_seconds
            ]
            self._user_attempts[user_id] = attempts
            user_retry = self._user_retry(attempts, now)

            if league_retry > 0 or user_retry > 0:
                return RefreshRateLimitDecision(
                    allowed=False, retry_after=max(league_retry, user_retry)
                )

            self._last_league_refresh[league_id] = now
            attempts.append(now)
            return RefreshRateLimitDecision(allowed=True, retry_after=0)

    def reset(self) -> None:
        """Forget every counter (used by tests and administrative resets)."""
        with self._lock:
            self._last_league_refresh.clear()
            self._user_attempts.clear()

    def _league_retry(self, league_id: int, now: float) -> int:
        """Return whole seconds until this league may refresh again, or zero when allowed."""
        last = self._last_league_refresh.get(league_id)
        if last is None or now >= last + self._league_interval_seconds:
            return 0
        return max(1, math.ceil(last + self._league_interval_seconds - now))

    def _user_retry(self, attempts: list[float], now: float) -> int:
        """Return whole seconds until this user's oldest attempt leaves the window, or zero."""
        if len(attempts) < self._user_limit:
            return 0
        return max(1, math.ceil(attempts[0] + self._user_window_seconds - now))
