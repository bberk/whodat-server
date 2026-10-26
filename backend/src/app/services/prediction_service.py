"""Playoff odds: exact snapshot inputs, digest-keyed cache, and Wilson intervals.

The service reads stored season data through
:class:`~app.services.standings_service.StandingsService` and runs the pure simulator in
:mod:`app.domain.predictions`. It never writes to the database. Only the league's latest stored
season can be simulated; a prior season is rejected before its snapshot is read or the cache is
consulted. The result is cached in-process by input digest, iteration count, seed, team-strength
weight, and model version, so repeated page loads do not recompute the same league season.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from sqlalchemy.orm import Session

from app.domain.predictions import (
    DEFAULT_STRENGTH_WEIGHT,
    MODEL_VERSION,
    RESIDUAL_MIX_GAMES,
    SHRINK_GAMES,
    PredictionReason,
    PredictionUnavailable,
    RemainingWeek,
    SeasonPredictionInputs,
    SeasonSimulation,
    SeededDrawSource,
    TeamSeasonTotals,
    normalize_strength_weight,
    simulate_season,
)
from app.services.standings_service import PredictionSnapshot, StandingsService

#: Iterations a request uses when it does not ask for a count.
DEFAULT_ITERATIONS = 10_000

#: Smallest accepted request; a single simulated season is still meaningful.
MIN_ITERATIONS = 1

#: Largest accepted request; protects the process from a CPU-exhaustion request.
MAX_ITERATIONS = 100_000

#: Largest iteration count a regular member may request.
MEMBER_MAX_ITERATIONS = 10_000

#: Largest iteration count an admin may request.
ADMIN_MAX_ITERATIONS = MAX_ITERATIONS

#: Largest accepted explicit seed (0 .. 2**31-1).
MAX_SEED = (1 << 31) - 1

#: Cache lifetime. A changed input digest always misses, so the TTL only bounds memory.
CACHE_TTL_SECONDS = 1_800.0

#: Number of distinct (league, season, input, iterations, seed, weight) results kept.
CACHE_MAX_ENTRIES = 64

#: Member-only payloads must not be cached by a shared proxy.
CACHE_CONTROL = "private, max-age=300"

_Z_95 = Decimal("1.959963984540054")

#: The account role that may request the larger iteration cap.
_ADMIN_ROLE = "admin"


def iterations_cap_for_role(role: str) -> int:
    """Return the largest iteration count an authenticated account role may request.

    Regular members are capped at :data:`MEMBER_MAX_ITERATIONS`; admins may use the full
    :data:`MAX_ITERATIONS`. The route enforces the cap, and the frontend shows the same maximum.
    """
    return ADMIN_MAX_ITERATIONS if role == _ADMIN_ROLE else MEMBER_MAX_ITERATIONS


@dataclass(frozen=True)
class ModelMetadata:
    """The versioned score-model parameters the API exposes for reproducibility."""

    version: str = MODEL_VERSION
    shrink_games: int = SHRINK_GAMES
    residual_mix_games: int = RESIDUAL_MIX_GAMES
    score_precision: str = "0.01"
    tiebreak_uses_points_for: bool = True


MODEL = ModelMetadata()


@dataclass(frozen=True)
class Probability:
    """An estimated probability and its Wilson 95% interval, as exact Decimals."""

    value: Decimal
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class TeamOdds:
    """One team's playoff, bye, division-title, and championship estimates."""

    team_id: int
    team_name: str
    division: str
    playoff: Probability
    bye: Probability
    division_title: Probability
    championship: Probability


@dataclass(frozen=True)
class PlayoffOdds:
    """The playoff-odds result for one league season.

    ``status="unavailable"`` carries a ``reason`` and no teams. A finished regular season still
    projects its bracket from the final seeds, so ``iterations`` is the requested sample count.
    """

    league_id: int
    season: int
    status: Literal["ok", "unavailable"]
    reason: PredictionReason | None
    iterations: int
    seed: int | None
    strength_weight: Decimal
    input_version: str
    confidence: Literal["low", "normal"] | None
    completed_weeks: int
    remaining_weeks: tuple[int, ...]
    playoff_field: int | None
    division_count: int
    teams: tuple[TeamOdds, ...]


@dataclass(frozen=True)
class _CacheKey:
    """Everything that can change a simulation result."""

    league_id: int
    season: int
    input_digest: str
    iterations: int
    seed: int
    model_version: str
    strength_weight: str


@dataclass(frozen=True)
class _CacheEntry:
    """One cached result and the monotonic instant it expires."""

    odds: PlayoffOdds
    expires_at: float


class PredictionCache:
    """A bounded, thread-safe LRU cache with a per-key single-flight computation lock.

    Two concurrent first requests for the same key run the simulator once; other keys compute in
    parallel. The clock is injectable so tests can expire entries without sleeping.
    """

    def __init__(
        self,
        *,
        max_entries: int = CACHE_MAX_ENTRIES,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the cache; ``clock`` returns monotonic seconds."""
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._locks: dict[_CacheKey, threading.Lock] = {}
        self._guard = threading.Lock()

    def get_or_compute(self, key: _CacheKey, compute: Callable[[], PlayoffOdds]) -> PlayoffOdds:
        """Return the cached result for ``key`` or compute and store it exactly once."""
        with self._guard:
            cached = self._entry(key)
            if cached is not None:
                return cached
            key_lock = self._locks.setdefault(key, threading.Lock())

        with key_lock:
            with self._guard:
                cached = self._entry(key)
                if cached is not None:
                    return cached
            odds = compute()
            with self._guard:
                self._entries[key] = _CacheEntry(
                    odds=odds, expires_at=self._clock() + self._ttl_seconds
                )
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
                self._prune_locks()
            return odds

    def clear(self) -> None:
        """Forget every cached result (used by tests and administrative resets)."""
        with self._guard:
            self._entries.clear()
            self._locks.clear()

    def _entry(self, key: _CacheKey) -> PlayoffOdds | None:
        """Return a live entry and refresh its LRU position, or drop an expired one."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry.odds

    def _prune_locks(self) -> None:
        """Drop lock objects whose keys are no longer cached and whose lock is idle."""
        if len(self._locks) <= self._max_entries * 2:
            return
        self._locks = {
            key: lock for key, lock in self._locks.items() if key in self._entries or lock.locked()
        }


_DEFAULT_CACHE = PredictionCache()


class PredictionService:
    """Compute and cache playoff odds for one stored league season."""

    def __init__(
        self,
        session: Session,
        *,
        cache: PredictionCache | None = None,
        standings: StandingsService | None = None,
    ) -> None:
        """Bind the service to a caller-owned session and an optional cache."""
        self._standings = standings if standings is not None else StandingsService(session)
        self._cache = cache if cache is not None else _DEFAULT_CACHE

    def get_playoff_odds(
        self,
        league_id: int,
        season: int,
        *,
        iterations: int = DEFAULT_ITERATIONS,
        seed: int | None = None,
        strength_weight: Decimal = DEFAULT_STRENGTH_WEIGHT,
    ) -> PlayoffOdds:
        """Return the cached or freshly simulated playoff odds for a league season.

        Only the league's latest stored season is accepted: a prior stored season raises
        :class:`~app.services.standings_service.SeasonNotCurrentError` before any snapshot is
        read, any cache entry is consulted, or any simulation runs. Unknown leagues and unstored
        seasons keep raising the standings-service not-found errors.

        ``iterations`` must be within 1-100,000, ``seed`` must be 0..2**31-1 when supplied, and
        ``strength_weight`` must be a finite decimal in 0..10. The route additionally caps
        ``iterations`` by the authenticated role. An omitted seed is derived from the input digest,
        the iteration count, and the model version, so the same data and parameters return the same
        numbers on every page load.
        """
        if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
            raise ValueError(f"iterations must be between {MIN_ITERATIONS} and {MAX_ITERATIONS}")
        if seed is not None and not 0 <= seed <= MAX_SEED:
            raise ValueError(f"seed must be between 0 and {MAX_SEED}")
        weight_text = format_strength_weight(strength_weight)

        self._standings.require_current_season(league_id, season)
        snapshot = self._standings.get_prediction_snapshot(league_id, season)
        digest = input_digest(snapshot, strength_weight=strength_weight)
        effective_seed = seed if seed is not None else derive_seed(digest, iterations)
        key = _CacheKey(
            league_id=league_id,
            season=season,
            input_digest=digest,
            iterations=iterations,
            seed=effective_seed,
            model_version=MODEL_VERSION,
            strength_weight=weight_text,
        )
        return self._cache.get_or_compute(
            key,
            lambda: _compute(
                snapshot,
                digest=digest,
                iterations=iterations,
                seed=effective_seed,
                strength_weight=strength_weight,
            ),
        )


def format_strength_weight(value: Decimal) -> str:
    """Return the canonical text of a team-strength weight, or raise ``ValueError``.

    Canonical text makes ``1``, ``1.0``, and ``1.00`` the same cache key and the same digest input,
    while keeping the exact decimal the caller sent. Out-of-range, non-finite, and over-precise
    values are rejected here as well as in the route, so no caller reaches the simulator with them.
    """
    return format(normalize_strength_weight(value), "f")


def _compute(
    snapshot: PredictionSnapshot,
    *,
    digest: str,
    iterations: int,
    seed: int,
    strength_weight: Decimal,
) -> PlayoffOdds:
    """Run the pure simulator once and project its counts into probabilities."""
    outcome = simulate_season(
        _simulation_inputs(snapshot, strength_weight),
        iterations=iterations,
        draws=SeededDrawSource(seed),
        bracket_draws=SeededDrawSource(derive_bracket_seed(seed)),
    )
    if isinstance(outcome, PredictionUnavailable):
        return PlayoffOdds(
            league_id=snapshot.league_id,
            season=snapshot.season,
            status="unavailable",
            reason=outcome.reason,
            iterations=0,
            seed=None,
            strength_weight=strength_weight,
            input_version=digest,
            confidence=None,
            completed_weeks=len(snapshot.counted_weeks),
            remaining_weeks=tuple(week.week for week in snapshot.remaining_weeks),
            playoff_field=snapshot.playoff_team_count,
            division_count=_division_count(snapshot.teams),
            teams=(),
        )
    return _result_odds(
        snapshot, outcome, digest=digest, seed=seed, strength_weight=strength_weight
    )


def _result_odds(
    snapshot: PredictionSnapshot,
    simulation: SeasonSimulation,
    *,
    digest: str,
    seed: int,
    strength_weight: Decimal,
) -> PlayoffOdds:
    """Build probability rows; a finished season has exact seeding but a projected champion."""
    samples = simulation.iterations
    teams = tuple(
        TeamOdds(
            team_id=team.team_id,
            team_name=team.team_name,
            division=team.division,
            playoff=_probability(team.playoff_count, samples),
            bye=_probability(team.bye_count, samples),
            division_title=_probability(team.division_title_count, samples),
            championship=_probability(team.championship_count, samples),
        )
        for team in simulation.teams
    )
    return PlayoffOdds(
        league_id=snapshot.league_id,
        season=snapshot.season,
        status="ok",
        reason=None,
        iterations=samples,
        seed=seed,
        strength_weight=strength_weight,
        input_version=digest,
        confidence=simulation.confidence,
        completed_weeks=simulation.completed_weeks,
        remaining_weeks=simulation.remaining_weeks,
        playoff_field=simulation.playoff_field,
        division_count=simulation.division_count,
        teams=teams,
    )


def _simulation_inputs(
    snapshot: PredictionSnapshot, strength_weight: Decimal
) -> SeasonPredictionInputs:
    """Project the service snapshot into the domain's immutable input type."""
    return SeasonPredictionInputs(
        teams=snapshot.teams,
        counted_weeks=snapshot.counted_weeks,
        remaining_weeks=snapshot.remaining_weeks,
        regular_season_length=snapshot.regular_season_length,
        playoff_team_count=snapshot.playoff_team_count,
        cup_week=snapshot.cup_week,
        strength_weight=strength_weight,
    )


def _probability(count: int, samples: int) -> Probability:
    """Return ``count / samples`` and its Wilson 95% interval."""
    if samples < 1:
        raise ValueError("samples must be positive")
    value = Decimal(count) / Decimal(samples)
    low, high = wilson_interval(count, samples)
    return Probability(value=value, low=low, high=high)


def wilson_interval(count: int, samples: int) -> tuple[Decimal, Decimal]:
    """Return the Wilson score 95% interval for ``count`` successes in ``samples`` trials.

    Wilson behaves correctly at 0% and 100%, where a normal approximation collapses. The inputs
    are integers and the arithmetic uses ``Decimal``; no binary float is involved.
    """
    if samples < 1:
        raise ValueError("samples must be positive")
    if not 0 <= count <= samples:
        raise ValueError("count must be between 0 and samples")

    p = Decimal(count) / Decimal(samples)
    z_squared = _Z_95 * _Z_95
    denominator = 1 + z_squared / Decimal(samples)
    center = (p + z_squared / (2 * Decimal(samples))) / denominator
    variance = p * (1 - p) / Decimal(samples) + z_squared / (4 * Decimal(samples) ** 2)
    margin = _Z_95 * variance.sqrt() / denominator
    return max(Decimal(0), center - margin), min(Decimal(1), center + margin)


def derive_seed(digest: str, iterations: int) -> int:
    """Derive a stable seed from the input digest, iteration count, and model version."""
    payload = f"{digest}:{iterations}:{MODEL_VERSION}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (MAX_SEED + 1)


def derive_bracket_seed(seed: int) -> int:
    """Derive the projected bracket's own draw seed from the regular-season seed.

    A separate stream keeps the regular-season draw order unchanged from the previous model, so a
    team-strength weight of ``1`` reproduces the earlier regular-season counts exactly; only the
    newly projected bracket consumes these draws. The derivation is stable for an explicit or
    derived seed and includes the model version.
    """
    payload = f"bracket:{seed}:{MODEL_VERSION}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (MAX_SEED + 1)


def input_digest(
    snapshot: PredictionSnapshot, *, strength_weight: Decimal = DEFAULT_STRENGTH_WEIGHT
) -> str:
    """Return a canonical SHA-256 digest of the simulation inputs only.

    ``last_refreshed_at`` is deliberately absent: a refresh that changes nothing keeps the cache.
    A score, pairing, cup week, playoff field, division, team name, current total, or team-strength
    weight change does invalidate it.
    """
    payload = {
        "league_id": snapshot.league_id,
        "season": snapshot.season,
        "regular_season_length": snapshot.regular_season_length,
        "cup_week": snapshot.cup_week,
        "playoff_team_count": snapshot.playoff_team_count,
        "strength_weight": format_strength_weight(strength_weight),
        "teams": [
            _team_payload(team) for team in sorted(snapshot.teams, key=lambda item: item.team_id)
        ],
        "counted_weeks": [
            {
                "week": week.week,
                "scores": [
                    {"team_id": score.team_id, "points": format(score.points, "f")}
                    for score in sorted(week.scores, key=lambda item: item.team_id)
                ],
            }
            for week in sorted(snapshot.counted_weeks, key=lambda item: item.week)
        ],
        "remaining_weeks": [
            _remaining_week_payload(week)
            for week in sorted(snapshot.remaining_weeks, key=lambda item: item.week)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _team_payload(team: TeamSeasonTotals) -> dict[str, object]:
    """Canonical digest fields for one team and its current exact totals."""
    return {
        "team_id": team.team_id,
        "team_name": team.team_name,
        "division": team.division,
        "vp": _fraction_text(team.vp),
        "wins": team.wins,
        "points_for": format(team.points_for, "f"),
    }


def _remaining_week_payload(week: RemainingWeek) -> dict[str, object]:
    """Canonical digest fields for one remaining week and its pairings."""
    return {
        "week": week.week,
        "is_playoff": week.is_playoff,
        "matchups": [
            {"home": matchup.home_team_id, "away": matchup.away_team_id}
            for matchup in sorted(
                week.matchups,
                key=lambda item: (item.home_team_id, item.away_team_id or -1),
            )
        ],
    }


def _fraction_text(value: Fraction) -> str:
    """Render a Fraction as a stable canonical string."""
    return f"{value.numerator}/{value.denominator}"


def _division_count(teams: tuple[TeamSeasonTotals, ...]) -> int:
    """Count distinct non-empty divisions without inventing a division for a team."""
    return len(
        {team.division for team in teams if team.division is not None and team.division.strip()}
    )


def clear_prediction_cache() -> None:
    """Clear the application-wide cache (used by tests and administrative resets)."""
    _DEFAULT_CACHE.clear()
