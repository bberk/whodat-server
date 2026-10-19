"""Tests for the in-process auth rate limiter (AC-AU-11)."""

from __future__ import annotations

import pytest
from fastapi import Request

from app.api.rate_limit import (
    AUTH_RATE_LIMIT,
    AUTH_RATE_WINDOW_SECONDS,
    RateLimiter,
    request_rate_limit_key,
)


class FakeClock:
    """A deterministic monotonic clock for fixed-window tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request(host: str = "203.0.113.5", path: str = "/api/v1/auth/login") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": [],
            "client": (host, 50000),
            "server": ("testserver", 80),
        }
    )


def test_documented_defaults() -> None:
    assert AUTH_RATE_LIMIT == 10
    assert AUTH_RATE_WINDOW_SECONDS == 60.0


def test_requests_up_to_the_limit_are_allowed() -> None:
    limiter = RateLimiter(clock=FakeClock())

    decisions = [limiter.check("client|signup") for _ in range(AUTH_RATE_LIMIT)]

    assert all(decision.allowed for decision in decisions)
    assert decisions[0].remaining == AUTH_RATE_LIMIT - 1
    assert decisions[-1].remaining == 0


def test_request_over_the_limit_is_denied_with_retry_after() -> None:
    clock = FakeClock(start=10.5)
    limiter = RateLimiter(limit=2, clock=clock)

    assert limiter.check("key").allowed is True
    assert limiter.check("key").allowed is True
    denied = limiter.check("key")

    assert denied.allowed is False
    assert denied.remaining == 0
    assert denied.retry_after == 50


def test_window_resets_after_the_configured_duration() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, clock=clock)
    assert limiter.check("key").allowed is True
    assert limiter.check("key").allowed is False

    clock.advance(60)
    assert limiter.check("key").allowed is True


def test_retry_after_is_never_zero() -> None:
    clock = FakeClock(start=59.5)
    limiter = RateLimiter(limit=1, clock=clock)
    limiter.check("key")

    denied = limiter.check("key")

    assert denied.allowed is False
    assert denied.retry_after == 1


def test_keys_are_independent() -> None:
    limiter = RateLimiter(limit=1, clock=FakeClock())

    assert limiter.check("client-a|signup").allowed is True
    assert limiter.check("client-b|signup").allowed is True
    assert limiter.check("client-a|signup").allowed is False
    assert limiter.check("client-b|signup").allowed is False


def test_routes_for_one_client_have_separate_buckets() -> None:
    limiter = RateLimiter(limit=1, clock=FakeClock())

    assert limiter.check("client|/api/v1/auth/signup").allowed is True
    assert limiter.check("client|/api/v1/auth/login").allowed is True
    assert limiter.check("client|/api/v1/auth/signup").allowed is False


def test_reset_forgets_all_counters() -> None:
    limiter = RateLimiter(limit=1, clock=FakeClock())
    limiter.check("key")
    assert limiter.check("key").allowed is False

    limiter.reset()

    assert limiter.check("key").allowed is True


def test_elapsed_windows_are_pruned_when_the_table_is_full() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, clock=clock, max_keys=1)
    limiter.check("old-key")

    clock.advance(60)
    limiter.check("new-key")

    assert list(limiter._entries) == ["new-key"]


def test_table_stays_bounded_when_many_keys_share_one_window() -> None:
    limiter = RateLimiter(limit=1, clock=FakeClock(), max_keys=2)
    limiter.check("first")
    limiter.check("second")
    limiter.check("third")

    assert list(limiter._entries) == ["second", "third"]


def test_request_key_combines_client_address_and_path() -> None:
    request = _request(host="198.51.100.7", path="/api/v1/auth/signup")

    assert request_rate_limit_key(request) == "198.51.100.7|/api/v1/auth/signup"
    assert request_rate_limit_key(request, route="login") == "198.51.100.7|login"


def test_request_key_ignores_x_forwarded_for() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/login",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", b"198.51.100.99")],
            "client": ("203.0.113.5", 50000),
            "server": ("testserver", 80),
        }
    )

    assert request_rate_limit_key(request) == "203.0.113.5|/api/v1/auth/login"


def test_request_key_without_a_client_address_uses_unknown() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/login",
            "query_string": b"",
            "headers": [],
            "client": None,
            "server": ("testserver", 80),
        }
    )

    assert request_rate_limit_key(request) == "unknown|/api/v1/auth/login"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit"),
        ({"window_seconds": 0}, "window_seconds"),
        ({"window_seconds": -1}, "window_seconds"),
        ({"max_keys": 0}, "max_keys"),
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RateLimiter(**kwargs)  # type: ignore[arg-type]
