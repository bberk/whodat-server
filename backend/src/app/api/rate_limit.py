"""In-process fixed-window rate limiting for the auth endpoints.

Limits are counted per key, where a key is the client IP plus the request route. The defaults are
10 requests per 60-second window for both ``POST /api/v1/auth/signup`` and
``POST /api/v1/auth/login``. Every attempt increments the window counter, so a rejected request
stays denied until the window resets; callers answer with HTTP 429 and the decision's
``Retry-After`` value in seconds.

The clock is injectable so tests can advance time deterministically. State lives in this process
only: it is neither shared between workers nor persisted, so a multi-instance deployment needs a
shared store (for example Redis) instead of this limiter. The same limitation applies to several
Uvicorn workers behind one process supervisor.

Keys use the direct peer address (``request.client.host``), never ``X-Forwarded-For`` on its own.
Behind a reverse proxy or load balancer, configure the proxy and the ASGI server (for example
Uvicorn ``--proxy-headers`` with trusted hosts, or an equivalent middleware) to present the real
client address; otherwise every client shares the proxy's address and therefore one bucket.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

#: Requests allowed per key per window on the auth endpoints.
AUTH_RATE_LIMIT = 10

#: Length of the fixed window in seconds.
AUTH_RATE_WINDOW_SECONDS = 60.0

#: Tracked keys are pruned once the table grows beyond this size.
_MAX_TRACKED_KEYS = 10_000


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of one rate-limit check."""

    allowed: bool
    retry_after: int
    remaining: int


@dataclass
class _Window:
    """The counter for one key in one fixed window."""

    window_index: int
    count: int


class RateLimiter:
    """A thread-safe, injectable-clock fixed-window limiter.

    Each distinct key gets a counter that resets when the window index changes. :meth:`check`
    prunes elapsed windows and, if the table is still at capacity, drops the oldest key so process
    memory stays bounded even when many addresses arrive in one window.
    """

    def __init__(
        self,
        *,
        limit: int = AUTH_RATE_LIMIT,
        window_seconds: float = AUTH_RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = _MAX_TRACKED_KEYS,
    ) -> None:
        """Configure the limiter; ``clock`` returns seconds and never moves backwards in tests."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self._limit = limit
        self._window_seconds = float(window_seconds)
        self._clock = clock
        self._max_keys = max_keys
        self._entries: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> RateLimitDecision:
        """Count one request for ``key`` and report whether it is allowed.

        The first ``limit`` requests in a window are allowed; every later request in the same
        window is denied until it expires. ``retry_after`` is the number of whole seconds until
        the window closes (at least one).
        """
        now = float(self._clock())
        window_index = int(now // self._window_seconds)
        with self._lock:
            if len(self._entries) >= self._max_keys:
                self._prune(window_index)
            entry = self._entries.get(key)
            if entry is None or entry.window_index != window_index:
                entry = _Window(window_index=window_index, count=0)
                self._entries[key] = entry
            entry.count += 1
            allowed = entry.count <= self._limit
            remaining = max(self._limit - entry.count, 0)
            retry_after = 0
            if not allowed:
                retry_after = max(1, math.ceil((window_index + 1) * self._window_seconds - now))
        return RateLimitDecision(allowed=allowed, retry_after=retry_after, remaining=remaining)

    def reset(self) -> None:
        """Forget every counter (used by tests and administrative resets)."""
        with self._lock:
            self._entries.clear()

    def _prune(self, current_window: int) -> None:
        """Drop elapsed counters, then the oldest key if the table is still at capacity.

        Dropping an in-window key gives that client a fresh counter; the bound protects process
        memory when many addresses arrive in one window.
        """
        stale = [key for key, entry in self._entries.items() if entry.window_index < current_window]
        for key in stale:
            del self._entries[key]
        while len(self._entries) >= self._max_keys:
            del self._entries[next(iter(self._entries))]


def request_rate_limit_key(request: Request, *, route: str | None = None) -> str:
    """Return ``"<client ip>|<route>"`` for the request.

    ``route`` defaults to the request path. The client address is the direct peer address;
    ``X-Forwarded-For`` is deliberately not trusted here. A deployment behind a proxy must
    configure the proxy and ASGI server to expose the real client address.
    """
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"{host}|{route if route is not None else request.url.path}"
