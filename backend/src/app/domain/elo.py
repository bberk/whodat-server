"""Pure Elo rating history for a league.

This module implements the rating model behind the History page. It is deliberately pure: it
talks only in ``Decimal`` values, caller-supplied team keys, and season/week records, and it
imports nothing from the database, HTTP, provider, clock, or randomness layers.

Model
-----
Every franchise starts at ``config.starting_rating`` (1500 by default). For a matchup between
teams ``a`` and ``b`` the expected score for ``a`` is::

    E_a = 1 / (1 + 10 ** ((R_b - R_a) / 400))

and the update is::

    R_a' = R_a + K_effective * (S_a - E_a)
    R_b' = R_b - K_effective * (S_a - E_a)

where ``S_a`` is 1 for a win, 0.5 for a tie and 0 for a loss. Both teams use the same signed
delta, so a decisive matchup is exactly zero-sum and a tie transfers the difference in the
expected scores. ``K_effective`` adds a capped margin bonus::

    K_effective = K * (1 + margin_weight * min(|margin|, margin_cap) / margin_cap)

The margin is the absolute difference in fantasy points; a tie has a margin of zero and therefore
uses the base K. Before each new stored season, every returning franchise regresses toward the
starting rating::

    R' = start + (R - start) * (1 - season_regression)

A franchise that is absent for one or more stored seasons performs one regression per missed
season boundary when it returns. A new franchise starts at the configured starting rating, even
when it first appears mid-history.

Modes
-----
``actual_schedule``
    Each stored head-to-head matchup updates both teams. Cup weeks are skipped entirely because
    they have no head-to-head result. Byes (a matchup with no away team) update nobody. A team
    that appears in more than one matchup in a week is updated in deterministic matchup order.

``round_robin``
    Every completed regular-season week counts, including cup weeks. Using the ratings at the
    start of the week, every unordered pair of teams is evaluated, each team's pairwise deltas are
    summed, and each team receives its *average* pairwise delta for the week::

        delta_i = (1 / (N - 1)) * sum_over_j K_effective(i, j) * (S_ij - E_ij)

    The average keeps a team's weekly movement comparable to one normal matchup instead of
    letting a big roster gain several times as much as a small one. Only start-of-week ratings are
    read while computing the deltas, so matchup order inside a week cannot change the result. A
    round-robin week needs a stored score for every team in that season's roster; otherwise the
    week is a flat slot and the caller should report a warning.

Playoffs and incomplete weeks are excluded by the caller (and defended here): a week marked
playoff or incomplete is ignored in both modes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

#: Internal decimal precision. Kept comfortably above the two decimals the API displays so that
#: week-to-week rounding never accumulates into a visible difference.
PRECISION = 28

DEFAULT_STARTING_RATING = Decimal("1500")
DEFAULT_K_FACTOR = Decimal("24")
DEFAULT_MARGIN_WEIGHT = Decimal("0.25")
DEFAULT_MARGIN_CAP = Decimal("50")
DEFAULT_SEASON_REGRESSION = Decimal(1) / Decimal(3)

EloMode = Literal["actual_schedule", "round_robin"]
MODES: frozenset[str] = frozenset({"actual_schedule", "round_robin"})


@dataclass(frozen=True)
class EloConfig:
    """Per-league rating settings, validated against the documented ranges.

    The defaults match the product defaults: start at 1500, K = 24, a margin bonus of up to 25%
    capped at 50 points, and a one-third regression toward the starting rating between seasons.
    """

    starting_rating: Decimal = DEFAULT_STARTING_RATING
    k_factor: Decimal = DEFAULT_K_FACTOR
    margin_weight: Decimal = DEFAULT_MARGIN_WEIGHT
    margin_cap: Decimal = DEFAULT_MARGIN_CAP
    season_regression: Decimal = DEFAULT_SEASON_REGRESSION

    def __post_init__(self) -> None:
        if not Decimal("1000") <= self.starting_rating <= Decimal("2000"):
            raise ValueError("starting_rating must be between 1000 and 2000")
        if not Decimal("1") <= self.k_factor <= Decimal("100"):
            raise ValueError("k_factor must be between 1 and 100")
        if not Decimal("0") <= self.margin_weight <= Decimal("1"):
            raise ValueError("margin_weight must be between 0 and 1")
        if not Decimal("1") <= self.margin_cap <= Decimal("200"):
            raise ValueError("margin_cap must be between 1 and 200")
        if not Decimal("0") <= self.season_regression <= Decimal("1"):
            raise ValueError("season_regression must be between 0 and 1")


@dataclass(frozen=True)
class EloMatch:
    """One stored head-to-head matchup, independent of provider identifiers."""

    home_key: str
    away_key: str | None
    home_points: Decimal
    away_points: Decimal | None = None
    #: Deterministic tiebreaker for a team that appears in more than one matchup in a week.
    order: int = 0


@dataclass(frozen=True)
class EloWeek:
    """One completed regular-season week's inputs.

    ``scores`` is the complete roster's score list for round-robin mode. The service passes every
    team it knows for the week; a missing team makes the round-robin week ineligible rather than
    silently comparing a partial roster.
    """

    season: int
    week: int
    is_cup_week: bool = False
    is_playoff: bool = False
    is_complete: bool = True
    matches: tuple[EloMatch, ...] = ()
    scores: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True)
class SeasonInfo:
    """One stored season's roster, ordered chronologically by the caller."""

    season: int
    team_keys: tuple[str, ...]


@dataclass(frozen=True)
class EloWeekPoint:
    """One chart slot: a completed regular-season week, including cup weeks."""

    season: int
    week: int
    is_cup_week: bool
    is_season_start: bool
    rated: bool


@dataclass(frozen=True)
class SeasonBoundary:
    """The chart index of a season's first week (only emitted after the first season)."""

    season: int
    week_index: int


@dataclass(frozen=True)
class EloWeekReference:
    """The season and week where a peak or low occurred."""

    season: int
    week: int


@dataclass(frozen=True)
class EloSeasonRating:
    """One franchise's rating within a season, with the post-reset baseline."""

    season: int
    start_rating: Decimal
    end_rating: Decimal
    change: Decimal
    rated_weeks: int


@dataclass(frozen=True)
class EloTeamHistory:
    """One franchise's full running series and summary values.

    ``series`` is aligned with :attr:`EloHistory.weeks`. ``None`` means the franchise was not in
    that season, or had not yet played a rated week while it was still new. A string-valued point
    is the rating after that week (flat across cup weeks and byes in actual-schedule mode).
    """

    team_key: str
    first_season: int
    last_season: int
    series: tuple[Decimal | None, ...]
    seasons: tuple[EloSeasonRating, ...]
    current: Decimal
    last_change: Decimal
    season_change: Decimal
    peak: Decimal
    peak_at: EloWeekReference | None
    low: Decimal
    low_at: EloWeekReference | None
    rated_weeks: int


@dataclass(frozen=True)
class EloHistory:
    """The complete domain result for one mode and one league."""

    config: EloConfig
    mode: EloMode
    seasons: tuple[int, ...]
    weeks: tuple[EloWeekPoint, ...]
    season_boundaries: tuple[SeasonBoundary, ...]
    teams: tuple[EloTeamHistory, ...]
    unrated_teams: tuple[str, ...]


def expected_score(rating_a: Decimal, rating_b: Decimal) -> Decimal:
    """Return ``a``'s expected score against ``b`` using the standard Elo curve.

    Ratings are arbitrary relative values; the 400-point scale makes a 400-point advantage about
    a 10:1 expected result. The result is kept at :data:`PRECISION` decimal digits.
    """
    with localcontext() as context:
        context.prec = PRECISION
        difference = (rating_b - rating_a) / Decimal(400)
        return Decimal(1) / (Decimal(1) + Decimal(10) ** difference)


def margin_multiplier(margin: Decimal, config: EloConfig) -> Decimal:
    """Return the capped margin bonus multiplier (>= 1) for an absolute point margin."""
    if margin < 0:
        raise ValueError("margin must not be negative")
    capped = min(margin, config.margin_cap)
    with localcontext() as context:
        context.prec = PRECISION
        return Decimal(1) + config.margin_weight * capped / config.margin_cap


def effective_k(margin: Decimal, config: EloConfig) -> Decimal:
    """Return ``k_factor`` times the capped margin bonus for one matchup."""
    with localcontext() as context:
        context.prec = PRECISION
        return config.k_factor * margin_multiplier(margin, config)


def update_ratings(
    rating_a: Decimal,
    rating_b: Decimal,
    score_a: Decimal,
    margin: Decimal,
    config: EloConfig,
) -> tuple[Decimal, Decimal]:
    """Return the post-matchup ratings for both teams using the same signed delta.

    ``score_a`` is 1 for an ``a`` win, 0.5 for a tie and 0 for a loss. Using one delta for both
    sides makes every decisive matchup exactly zero-sum.
    """
    with localcontext() as context:
        context.prec = PRECISION
        expected = expected_score(rating_a, rating_b)
        delta = effective_k(margin, config) * (score_a - expected)
        return rating_a + delta, rating_b - delta


def regress_rating(rating: Decimal, config: EloConfig) -> Decimal:
    """Move one rating one season boundary toward the configured starting rating."""
    with localcontext() as context:
        context.prec = PRECISION
        return config.starting_rating + (rating - config.starting_rating) * (
            Decimal(1) - config.season_regression
        )


def _compare(points_a: Decimal, points_b: Decimal) -> Decimal:
    """Return the Elo result from ``a``'s perspective: win 1, tie 0.5, loss 0."""
    if points_a > points_b:
        return Decimal(1)
    if points_a < points_b:
        return Decimal(0)
    return Decimal("0.5")


def _ordered_matches(matches: Sequence[EloMatch]) -> list[EloMatch]:
    """Sort a week's matchups deterministically, including a stable id/order tiebreaker."""
    return sorted(
        matches,
        key=lambda match: (
            match.order,
            match.home_key,
            match.away_key if match.away_key is not None else "",
        ),
    )


def _apply_actual_week(
    week: EloWeek,
    ratings: dict[str, Decimal],
    config: EloConfig,
) -> tuple[bool, set[str]]:
    """Apply one actual-schedule week in place and return ``(rated, rated_team_keys)``."""
    if week.is_cup_week:
        return False, set()

    rated_keys: set[str] = set()
    for match in _ordered_matches(week.matches):
        if match.away_key is None or match.away_points is None:
            continue
        if match.home_key not in ratings or match.away_key not in ratings:
            continue
        score_a = _compare(match.home_points, match.away_points)
        margin = abs(match.home_points - match.away_points)
        home, away = update_ratings(
            ratings[match.home_key],
            ratings[match.away_key],
            score_a,
            margin,
            config,
        )
        ratings[match.home_key] = home
        ratings[match.away_key] = away
        rated_keys.add(match.home_key)
        rated_keys.add(match.away_key)

    return bool(rated_keys), rated_keys


def _apply_round_robin_week(
    week: EloWeek,
    roster: set[str],
    ratings: dict[str, Decimal],
    config: EloConfig,
) -> tuple[bool, set[str]]:
    """Apply one round-robin week from start-of-week ratings and average each team's deltas."""
    scores = {key: points for key, points in week.scores if key in roster}
    if len(scores) != len(roster) or len(scores) < 2:
        return False, set()

    start = {key: ratings[key] for key in scores}
    deltas = {key: Decimal(0) for key in scores}
    keys = sorted(scores)
    with localcontext() as context:
        context.prec = PRECISION
        for index, key_a in enumerate(keys):
            for key_b in keys[index + 1 :]:
                points_a = scores[key_a]
                points_b = scores[key_b]
                result_a = _compare(points_a, points_b)
                margin = abs(points_a - points_b)
                expected = expected_score(start[key_a], start[key_b])
                delta = effective_k(margin, config) * (result_a - expected)
                deltas[key_a] += delta
                deltas[key_b] -= delta

        divisor = Decimal(len(keys) - 1)
        for key in keys:
            ratings[key] = start[key] + deltas[key] / divisor

    return True, set(scores)


def compute_elo_history(
    weeks: Sequence[EloWeek],
    seasons: Sequence[SeasonInfo],
    config: EloConfig,
    *,
    mode: EloMode,
) -> EloHistory:
    """Compute every franchise's running rating history from stored weeks.

    Seasons are processed in ascending ``season`` order (not insertion order), so adding an older
    season retroactively changes later ratings. Season regression runs before the first week of
    each season. A franchise absent for a stored season regresses for each missed boundary when it
    returns. Only completed regular-season weeks supplied by the caller appear in the result;
    playoff and incomplete weeks are ignored defensively.

    Raises:
        ValueError: if ``mode`` is not ``actual_schedule`` or ``round_robin``.
    """
    if mode not in MODES:
        raise ValueError(f"unknown Elo mode {mode!r}")

    ordered_seasons = sorted(seasons, key=lambda item: item.season)
    all_keys = sorted({key for season in ordered_seasons for key in season.team_keys})

    week_points: list[EloWeekPoint] = []
    season_boundaries: list[SeasonBoundary] = []
    series: dict[str, list[Decimal | None]] = {key: [] for key in all_keys}
    ratings: dict[str, Decimal] = {}
    started: set[str] = set()
    last_seen: dict[str, int] = {}
    season_starts: dict[tuple[str, int], Decimal] = {}
    season_ends: dict[tuple[str, int], Decimal] = {}
    season_rated: dict[tuple[str, int], int] = {}
    last_change: dict[str, Decimal] = {key: Decimal(0) for key in all_keys}
    peak = {key: config.starting_rating for key in all_keys}
    low = {key: config.starting_rating for key in all_keys}
    peak_at: dict[str, EloWeekReference | None] = {key: None for key in all_keys}
    low_at: dict[str, EloWeekReference | None] = {key: None for key in all_keys}

    weeks_by_season: dict[int, list[EloWeek]] = {}
    for week in sorted(weeks, key=lambda item: (item.season, item.week)):
        weeks_by_season.setdefault(week.season, []).append(week)

    for index, season in enumerate(ordered_seasons):
        roster = set(season.team_keys)
        if not roster:
            continue

        for key in sorted(roster):
            if key in ratings:
                missed = index - last_seen[key]
                for _ in range(missed):
                    ratings[key] = regress_rating(ratings[key], config)
            else:
                ratings[key] = config.starting_rating
            last_seen[key] = index
            season_starts[(key, season.season)] = ratings[key]
            season_ends[(key, season.season)] = ratings[key]
            season_rated[(key, season.season)] = 0

        season_weeks = weeks_by_season.get(season.season, [])
        if season_weeks and week_points:
            season_boundaries.append(
                SeasonBoundary(season=season.season, week_index=len(week_points))
            )

        for week_index, week in enumerate(season_weeks):
            if week.is_playoff or not week.is_complete:
                continue
            before = dict(ratings)
            if mode == "actual_schedule":
                rated, rated_keys = _apply_actual_week(week, ratings, config)
            else:
                rated, rated_keys = _apply_round_robin_week(week, roster, ratings, config)

            started.update(rated_keys)
            point = EloWeekPoint(
                season=week.season,
                week=week.week,
                is_cup_week=week.is_cup_week,
                is_season_start=week_index == 0,
                rated=rated,
            )
            week_points.append(point)

            for key in all_keys:
                if key in roster and key in started:
                    value = ratings[key]
                    series[key].append(value)
                    reference = EloWeekReference(season=week.season, week=week.week)
                    if value > peak[key]:
                        peak[key] = value
                        peak_at[key] = reference
                    if value < low[key]:
                        low[key] = value
                        low_at[key] = reference
                    last_change[key] = value - before[key]
                else:
                    series[key].append(None)

            for key in rated_keys:
                season_rated[(key, season.season)] += 1

        for key in roster:
            season_ends[(key, season.season)] = ratings[key]

    team_seasons: dict[str, list[EloSeasonRating]] = {key: [] for key in all_keys}
    for key in all_keys:
        for season in ordered_seasons:
            if key not in season.team_keys:
                continue
            start = season_starts[(key, season.season)]
            end = season_ends[(key, season.season)]
            team_seasons[key].append(
                EloSeasonRating(
                    season=season.season,
                    start_rating=start,
                    end_rating=end,
                    change=end - start,
                    rated_weeks=season_rated[(key, season.season)],
                )
            )

    teams: list[EloTeamHistory] = []
    unrated: list[str] = []
    for key in all_keys:
        seasons_for_team = team_seasons[key]
        total_rated = sum(season.rated_weeks for season in seasons_for_team)
        if total_rated == 0:
            unrated.append(key)
            continue
        current = ratings[key]
        last_season = seasons_for_team[-1]
        teams.append(
            EloTeamHistory(
                team_key=key,
                first_season=seasons_for_team[0].season,
                last_season=last_season.season,
                series=tuple(series[key]),
                seasons=tuple(seasons_for_team),
                current=current,
                last_change=last_change[key],
                season_change=current - last_season.start_rating,
                peak=peak[key],
                peak_at=peak_at[key],
                low=low[key],
                low_at=low_at[key],
                rated_weeks=total_rated,
            )
        )

    teams.sort(key=lambda team: (team.first_season, team.team_key))
    unrated.sort(key=lambda key: (team_seasons[key][0].season, key))

    return EloHistory(
        config=config,
        mode=mode,
        seasons=tuple(season.season for season in ordered_seasons if season.team_keys),
        weeks=tuple(week_points),
        season_boundaries=tuple(season_boundaries),
        teams=tuple(teams),
        unrated_teams=tuple(unrated),
    )
