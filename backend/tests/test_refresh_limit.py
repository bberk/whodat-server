"""Tests for the league-refresh rate limiter and its application-wide wiring."""

from __future__ import annotations

import pytest

from app.api.refresh_limit import (
    RefreshRateLimiter,
    get_refresh_limiter,
    get_season_refresh_limiter,
)
from app.services.league_service import RefreshRateLimitDecision


class FakeClock:
    """A deterministic seconds clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_first_refresh_is_allowed_and_an_immediate_retry_is_denied() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock)

    first = limiter.check(league_id=1, user_id=10)
    denied = limiter.check(league_id=1, user_id=10)

    assert first == RefreshRateLimitDecision(allowed=True, retry_after=0)
    assert denied.allowed is False
    assert denied.retry_after == 300


def test_league_retry_after_counts_down_to_the_window_boundary() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock)
    limiter.check(league_id=7, user_id=10)

    clock.now = 299.0
    almost = limiter.check(league_id=7, user_id=10)

    clock.now = 300.0
    allowed = limiter.check(league_id=7, user_id=10)

    assert almost == RefreshRateLimitDecision(allowed=False, retry_after=1)
    assert allowed.allowed is True


def test_per_league_limits_are_independent() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock)
    limiter.check(league_id=1, user_id=10)

    assert limiter.check(league_id=2, user_id=10).allowed is True


def test_per_user_limit_allows_three_refreshes_per_hour() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock, league_interval_seconds=0.0)

    decisions = [limiter.check(league_id=league, user_id=10).allowed for league in range(1, 5)]

    assert decisions == [True, True, True, False]
    denied = limiter.check(league_id=99, user_id=10)
    assert denied.allowed is False
    assert denied.retry_after == 3600


def test_per_user_limit_is_independent_between_users() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock, league_interval_seconds=0.0)
    for _ in range(3):
        limiter.check(league_id=1, user_id=10)

    assert limiter.check(league_id=1, user_id=11).allowed is True


def test_denied_attempts_do_not_consume_quota() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock)
    limiter.check(league_id=1, user_id=10)
    for _ in range(5):
        assert limiter.check(league_id=1, user_id=10).allowed is False

    clock.now = 300.0
    assert limiter.check(league_id=1, user_id=10).allowed is True


def test_user_retry_after_tracks_the_oldest_attempt_leaving_the_window() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock, league_interval_seconds=0.0)
    for _ in range(3):
        assert limiter.check(league_id=1, user_id=10).allowed is True

    clock.now = 100.0
    denied = limiter.check(league_id=1, user_id=10)

    assert denied.allowed is False
    assert denied.retry_after == 3500


def test_reset_clears_both_limits() -> None:
    clock = FakeClock()
    limiter = RefreshRateLimiter(clock=clock, league_interval_seconds=0.0)
    for _ in range(3):
        limiter.check(league_id=1, user_id=10)
    assert limiter.check(league_id=1, user_id=10).allowed is False

    limiter.reset()

    assert limiter.check(league_id=1, user_id=10).allowed is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"league_interval_seconds": -1}, "negative"),
        ({"user_limit": 0}, "at least 1"),
        ({"user_window_seconds": 0}, "positive"),
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RefreshRateLimiter(**kwargs)


def test_application_limiter_is_a_process_singleton() -> None:
    assert get_refresh_limiter() is get_refresh_limiter()


def test_application_season_limiter_is_a_separate_process_singleton() -> None:
    assert get_season_refresh_limiter() is get_season_refresh_limiter()
    assert get_season_refresh_limiter() is not get_refresh_limiter()
