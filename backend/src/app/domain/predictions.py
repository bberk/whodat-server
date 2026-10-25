"""Pure Monte Carlo simulation of the remaining regular season.

The simulator starts from the exact current totals the standings page shows, samples each remaining
week's scores for every team, and applies the real Victory Point engine on an integer tick scale.
Past weeks are never re-sampled: only future scores and the resulting seeds are simulated.

The score model is a shrunk team strength plus an empirical residual bootstrap:

* ``mu_w`` is the league-week mean, ``mu_bar`` the grand mean, and ``s_bar_t`` a team's mean.
* ``delta_t = n_t / (n_t + 3) * (s_bar_t - mu_bar)`` shrinks a small sample toward the league.
* A two-way residual ``s_t,w - mu_w - (s_bar_t - mu_bar)`` removes both the week's environment and
  the team's average; a team's own residuals are used with probability ``n_t / (n_t + 4)``, else the
  pooled residuals. With fewer than two counted weeks (or no team with two observations) the
  simulator falls back to week-centred residuals and ``delta_t = 0``.

All scores are integer cents and all VP is integer ticks; no ``float`` appears in this module. A
draw source is injected so the function never imports or seeds a random-number generator itself.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from math import lcm
from typing import Literal, Protocol

from app.domain.vp_engine import week_h2h_ticks, week_rank_component_ticks

#: Model version. Any change to sampling, parameters, or draw order must bump this value.
MODEL_VERSION = "vp-mc-1"

#: Pseudo-games of shrinkage applied to a team's raw deviation from the league mean.
SHRINK_GAMES = 3

#: Pseudo-games of shrinkage applied to the own-residual mixture probability.
RESIDUAL_MIX_GAMES = 4

#: Completed weeks below this count make the estimate low-confidence.
LOW_CONFIDENCE_WEEKS = 4

#: A team with fewer observed weeks than this makes the estimate low-confidence.
LOW_CONFIDENCE_OBSERVATIONS = 3

type PredictionReason = Literal[
    "no_completed_weeks",
    "missing_playoff_field",
    "incomplete_schedule",
    "unsupported_division_shape",
]
type Confidence = Literal["low", "normal"]


@dataclass(frozen=True)
class TeamSeasonTotals:
    """One team's exact current totals and division, as the standings service reports them."""

    team_id: int
    team_name: str
    division: str | None
    vp: Fraction
    wins: int
    points_for: Decimal


@dataclass(frozen=True)
class CountedScore:
    """One observed team score in a counted week."""

    team_id: int
    points: Decimal


@dataclass(frozen=True)
class CountedWeek:
    """A completed regular-season week whose raw scores feed the model."""

    week: int
    scores: tuple[CountedScore, ...]


@dataclass(frozen=True)
class RemainingMatchup:
    """One stored future pairing; an absent away team is a bye."""

    home_team_id: int
    away_team_id: int | None


@dataclass(frozen=True)
class RemainingWeek:
    """A regular-season week that is not complete, with its full stored schedule."""

    week: int
    matchups: tuple[RemainingMatchup, ...]
    is_playoff: bool = False


@dataclass(frozen=True)
class SeasonPredictionInputs:
    """Everything the simulator needs for one league season."""

    teams: tuple[TeamSeasonTotals, ...]
    counted_weeks: tuple[CountedWeek, ...]
    remaining_weeks: tuple[RemainingWeek, ...]
    regular_season_length: int
    playoff_team_count: int | None
    cup_week: int | None


@dataclass(frozen=True)
class TeamPredictionCounts:
    """How often one team reached each outcome across the simulated seasons."""

    team_id: int
    team_name: str
    division: str
    playoff_count: int
    bye_count: int
    division_title_count: int


@dataclass(frozen=True)
class SeasonSimulation:
    """A completed simulation: per-team counts plus the metadata needed to present them.

    ``iterations`` is zero for a finished regular season, where the current table is the final
    answer and each count is exactly zero or one.
    """

    iterations: int
    teams: tuple[TeamPredictionCounts, ...]
    completed_weeks: int
    remaining_weeks: tuple[int, ...]
    playoff_field: int
    division_count: int
    bye_count: int
    confidence: Confidence
    scale: int
    base_points: tuple[Decimal, ...]
    observation_counts: tuple[int, ...]
    uses_two_way_residuals: bool
    pooled_residual_count: int


@dataclass(frozen=True)
class PredictionUnavailable:
    """The season cannot be simulated without inventing data; ``reason`` says why."""

    reason: PredictionReason


type PredictionOutcome = SeasonSimulation | PredictionUnavailable


class DrawSource(Protocol):
    """A deterministic source of bounded integers, injected so the domain owns no RNG state."""

    def next_below(self, upper: int) -> int:
        """Return an integer in ``0..upper-1``; ``upper`` is always positive."""
        ...


class SeededDrawSource:
    """A small SplitMix64-based draw source that is stable across Python versions.

    The simulator's reproducibility is part of its contract (AC-PO-06), so it does not depend on
    CPython's ``random`` implementation. Rejection sampling removes the modulo bias of a plain
    remainder without importing anything from the standard random module.
    """

    _MULTIPLIER_1 = 0xBF58476D1CE4E5B9
    _MULTIPLIER_2 = 0x94D049BB133111EB
    _INCREMENT = 0x9E3779B97F4A7C15
    _MASK = (1 << 64) - 1
    _RANGE = 1 << 64

    def __init__(self, seed: int) -> None:
        """Seed the generator; the state is the full 64-bit seed value."""
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self._state = seed & self._MASK

    def next_below(self, upper: int) -> int:
        """Return an unbiased integer below ``upper``."""
        if upper < 1:
            raise ValueError("upper must be positive")
        limit = self._RANGE - self._RANGE % upper
        while True:
            value = self._next_uint64()
            if value < limit:
                return value % upper

    def _next_uint64(self) -> int:
        """Advance the SplitMix64 state and return the mixed 64-bit value."""
        self._state = (self._state + self._INCREMENT) & self._MASK
        value = self._state
        value = ((value ^ (value >> 30)) * self._MULTIPLIER_1) & self._MASK
        value = ((value ^ (value >> 27)) * self._MULTIPLIER_2) & self._MASK
        return value ^ (value >> 31)


class DeterministicDrawSource:
    """A draw source that always returns zero, for a reproducible single-path simulation.

    It removes randomness without hiding it: every team draws the first residual in its pool, so the
    same inputs always produce the same one simulated season. The service uses a seeded source; this
    mode exists for diagnostics and for tests that need a fixed path.
    """

    def next_below(self, upper: int) -> int:
        """Return zero, which is valid for every positive ``upper``."""
        if upper < 1:
            raise ValueError("upper must be positive")
        return 0


@dataclass(frozen=True)
class _SimulatedWeek:
    """A remaining week reduced to opponent indices aligned with the team order."""

    week: int
    opponents: tuple[int | None, ...]
    is_cup_week: bool


@dataclass(frozen=True)
class _Prepared:
    """Validated simulation inputs and the estimated score model."""

    team_ids: tuple[int, ...]
    team_names: tuple[str, ...]
    divisions: tuple[str, ...]
    start_vp_ticks: tuple[int, ...]
    wins: tuple[int, ...]
    points_for_cents: tuple[int, ...]
    base_cents: tuple[int, ...]
    own_residuals: tuple[tuple[int, ...], ...]
    pooled_residuals: tuple[int, ...]
    observation_counts: tuple[int, ...]
    weeks: tuple[_SimulatedWeek, ...]
    playoff_field: int
    bye_count: int
    division_count: int
    scale: int
    confidence: Confidence
    completed_weeks: int
    base_points: tuple[Decimal, ...]
    uses_two_way_residuals: bool


def simulate_season(
    inputs: SeasonPredictionInputs,
    *,
    iterations: int,
    draws: DrawSource | None = None,
) -> PredictionOutcome:
    """Simulate ``iterations`` completions of the stored season and return per-team counts.

    A finished regular season (no remaining weeks) is evaluated once from the current totals and
    reports ``iterations=0``. Otherwise ``iterations`` must be positive; ``draws`` defaults to
    :class:`DeterministicDrawSource`, so a caller that wants seeded randomness passes a
    :class:`SeededDrawSource`. Missing or inconsistent inputs return an explicit
    :class:`PredictionUnavailable` instead of a guessed result. This function is pure and performs
    no I/O.
    """
    prepared = _prepare(inputs)
    if isinstance(prepared, PredictionUnavailable):
        return prepared
    if not prepared.weeks:
        return _finished_simulation(prepared)
    if iterations < 1:
        raise ValueError("iterations must be at least 1 while weeks remain")
    return _simulate(prepared, iterations, draws or DeterministicDrawSource())


def _prepare(inputs: SeasonPredictionInputs) -> _Prepared | PredictionUnavailable:
    """Validate the inputs and estimate the score model, or explain why it is unavailable."""
    if not inputs.teams or inputs.regular_season_length < 1:
        return PredictionUnavailable("incomplete_schedule")

    team_ids = tuple(team.team_id for team in inputs.teams)
    if len(set(team_ids)) != len(team_ids):
        return PredictionUnavailable("incomplete_schedule")

    divisions: list[str] = []
    for team in inputs.teams:
        division = team.division
        if division is None or not division.strip():
            return PredictionUnavailable("unsupported_division_shape")
        divisions.append(division)
    division_names = tuple(dict.fromkeys(divisions))
    division_count = len(division_names)

    playoff_field = inputs.playoff_team_count
    if (
        not isinstance(playoff_field, int)
        or isinstance(playoff_field, bool)
        or playoff_field < division_count
        or playoff_field > len(team_ids)
    ):
        return PredictionUnavailable("missing_playoff_field")

    if not _valid_week_coverage(inputs):
        return PredictionUnavailable("incomplete_schedule")
    if inputs.cup_week is not None and (
        isinstance(inputs.cup_week, bool)
        or not 1 <= inputs.cup_week <= inputs.regular_season_length
    ):
        return PredictionUnavailable("incomplete_schedule")
    if not inputs.counted_weeks:
        return PredictionUnavailable("no_completed_weeks")

    index_by_id = {team_id: index for index, team_id in enumerate(team_ids)}
    for week in inputs.counted_weeks:
        if not week.scores or any(score.team_id not in index_by_id for score in week.scores):
            return PredictionUnavailable("incomplete_schedule")

    weeks = _remaining_weeks(inputs, index_by_id)
    if weeks is None:
        return PredictionUnavailable("incomplete_schedule")

    model = _estimate_model(inputs.counted_weeks, team_ids)
    scale = _tick_scale(team_ids, inputs.teams)
    start_vp_ticks = tuple(_vp_ticks(team.vp, scale) for team in inputs.teams)
    wins = tuple(team.wins for team in inputs.teams)
    points_for_cents = tuple(_cents(team.points_for) for team in inputs.teams)
    confidence: Confidence = (
        "low"
        if len(inputs.counted_weeks) < LOW_CONFIDENCE_WEEKS
        or any(count < LOW_CONFIDENCE_OBSERVATIONS for count in model.observation_counts)
        else "normal"
    )
    return _Prepared(
        team_ids=team_ids,
        team_names=tuple(team.team_name for team in inputs.teams),
        divisions=tuple(divisions),
        start_vp_ticks=start_vp_ticks,
        wins=wins,
        points_for_cents=points_for_cents,
        base_cents=model.base_cents,
        own_residuals=model.own_residuals,
        pooled_residuals=model.pooled_residuals,
        observation_counts=model.observation_counts,
        weeks=weeks,
        playoff_field=playoff_field,
        bye_count=_bye_count(playoff_field, division_count),
        division_count=division_count,
        scale=scale,
        confidence=confidence,
        completed_weeks=len(inputs.counted_weeks),
        base_points=tuple(_points(cents) for cents in model.base_cents),
        uses_two_way_residuals=model.uses_two_way,
    )


def _valid_week_coverage(inputs: SeasonPredictionInputs) -> bool:
    """Require counted and remaining weeks to partition the regular season exactly once."""
    counted = [week.week for week in inputs.counted_weeks]
    remaining = [week.week for week in inputs.remaining_weeks]
    if len(set(counted)) != len(counted) or len(set(remaining)) != len(remaining):
        return False
    expected = set(range(1, inputs.regular_season_length + 1))
    return set(counted) | set(remaining) == expected


def _remaining_weeks(
    inputs: SeasonPredictionInputs, index_by_id: dict[int, int]
) -> tuple[_SimulatedWeek, ...] | None:
    """Validate every remaining week and reduce it to opponent indices.

    Every week must list each team exactly once, either in a matchup or as an explicit bye. A
    missing, duplicate, self, or unknown pairing and a playoff game inside the regular season are
    inconsistencies, not data to fill in.
    """
    team_count = len(index_by_id)
    all_indices = frozenset(range(team_count))
    weeks: list[_SimulatedWeek] = []
    for week in sorted(inputs.remaining_weeks, key=lambda item: item.week):
        if week.is_playoff:
            return None
        opponents: list[int | None] = [None] * team_count
        participants: list[int] = []
        for matchup in week.matchups:
            home = index_by_id.get(matchup.home_team_id)
            away = None if matchup.away_team_id is None else index_by_id.get(matchup.away_team_id)
            if home is None or (matchup.away_team_id is not None and away is None):
                return None
            if away == home:
                return None
            participants.append(home)
            opponents[home] = away
            if away is not None:
                participants.append(away)
                opponents[away] = home
        if len(participants) != team_count or frozenset(participants) != all_indices:
            return None
        weeks.append(
            _SimulatedWeek(
                week=week.week,
                opponents=tuple(opponents),
                is_cup_week=week.week == inputs.cup_week,
            )
        )
    return tuple(weeks)


@dataclass(frozen=True)
class _Model:
    """The estimated future-score distribution in integer cents."""

    base_cents: tuple[int, ...]
    own_residuals: tuple[tuple[int, ...], ...]
    pooled_residuals: tuple[int, ...]
    observation_counts: tuple[int, ...]
    uses_two_way: bool


def _estimate_model(counted_weeks: tuple[CountedWeek, ...], team_ids: tuple[int, ...]) -> _Model:
    """Estimate shrunk team bases and the empirical residual pools from counted scores."""
    observations: dict[int, list[tuple[int, Fraction]]] = {team_id: [] for team_id in team_ids}
    week_means: dict[int, Fraction] = {}
    for week in counted_weeks:
        values: list[Fraction] = []
        for score in week.scores:
            value = Fraction(score.points) * 100
            observations[score.team_id].append((week.week, value))
            values.append(value)
        week_means[week.week] = sum(values, Fraction(0)) / len(values)

    all_values = [value for team_obs in observations.values() for _, value in team_obs]
    grand_mean = sum(all_values, Fraction(0)) / len(all_values)
    observation_counts = tuple(len(observations[team_id]) for team_id in team_ids)

    team_raw_deviation: dict[int, Fraction] = {}
    for team_id in team_ids:
        team_observations = observations[team_id]
        team_mean = (
            sum((value for _, value in team_observations), Fraction(0)) / len(team_observations)
            if team_observations
            else grand_mean
        )
        team_raw_deviation[team_id] = team_mean - grand_mean

    two_way = len(counted_weeks) >= 2 and any(count >= 2 for count in observation_counts)
    own: dict[int, list[int]] = {team_id: [] for team_id in team_ids}
    pooled: list[int] = []
    if two_way:
        for team_id, count in zip(team_ids, observation_counts, strict=True):
            if count < 2:
                continue
            for week_number, value in observations[team_id]:
                residual = value - week_means[week_number] - team_raw_deviation[team_id]
                cents = _round_half_up(residual)
                pooled.append(cents)
                own[team_id].append(cents)
    else:
        for team_id in team_ids:
            for week_number, value in observations[team_id]:
                pooled.append(_round_half_up(value - week_means[week_number]))

    base_cents: list[int] = []
    for team_id, count in zip(team_ids, observation_counts, strict=True):
        deviation = (
            Fraction(count, count + SHRINK_GAMES) * team_raw_deviation[team_id]
            if two_way
            else Fraction(0)
        )
        base_cents.append(_round_half_up(grand_mean + deviation))

    return _Model(
        base_cents=tuple(base_cents),
        own_residuals=tuple(tuple(own[team_id]) for team_id in team_ids),
        pooled_residuals=tuple(pooled),
        observation_counts=observation_counts,
        uses_two_way=two_way,
    )


def _simulate(prepared: _Prepared, iterations: int, draws: DrawSource) -> SeasonSimulation:
    """Run the integer hot loop ``iterations`` times and tally each outcome."""
    team_count = len(prepared.team_ids)
    counts = [[0, 0, 0] for _ in range(team_count)]
    start_vp = prepared.start_vp_ticks
    start_wins = prepared.wins
    start_points = prepared.points_for_cents
    for _ in range(iterations):
        vp = list(start_vp)
        wins = list(start_wins)
        points_for = list(start_points)
        for week in prepared.weeks:
            scores = _draw_week(prepared, draws)
            top_half, high, low = week_rank_component_ticks(scores, prepared.scale)
            if week.is_cup_week:
                for index in range(team_count):
                    vp[index] += top_half[index] + high[index] + low[index]
            else:
                h2h = week_h2h_ticks(prepared.team_ids, scores, week.opponents, prepared.scale)
                for index in range(team_count):
                    vp[index] += top_half[index] + high[index] + low[index] + h2h[index]
                for index, opponent in enumerate(week.opponents):
                    if opponent is None or index >= opponent:
                        continue
                    if scores[index] > scores[opponent]:
                        wins[index] += 1
                    elif scores[index] < scores[opponent]:
                        wins[opponent] += 1
            for index in range(team_count):
                points_for[index] += scores[index]
        _tally(prepared, vp, wins, points_for, counts)
    return _result(prepared, counts, iterations=iterations)


def _finished_simulation(prepared: _Prepared) -> SeasonSimulation:
    """Return the exact final seeding of a finished regular season as zero/one counts."""
    counts = [[0, 0, 0] for _ in prepared.team_ids]
    _tally(
        prepared,
        list(prepared.start_vp_ticks),
        list(prepared.wins),
        list(prepared.points_for_cents),
        counts,
    )
    return _result(prepared, counts, iterations=0)


def _draw_week(prepared: _Prepared, draws: DrawSource) -> list[int]:
    """Draw one future score in integer cents for every team, including bye and cup-week teams.

    For a team with at least two observations, one draw selects both the own-versus-pooled mixture
    and the residual: ``n`` own outcomes per pooled entry and four pooled outcomes per entry give
    exactly ``n / (n + 4)`` own probability and a uniform residual inside each pool. This is the
    same distribution as two separate draws with half the generator calls.
    """
    scores: list[int] = []
    pooled = prepared.pooled_residuals
    pooled_size = len(pooled)
    next_below = draws.next_below
    for index, count in enumerate(prepared.observation_counts):
        if count >= 2:
            own = prepared.own_residuals[index]
            own_span = count * pooled_size
            draw = next_below((count + RESIDUAL_MIX_GAMES) * pooled_size)
            if draw < own_span:
                residual = own[draw // pooled_size]
            else:
                residual = pooled[(draw - own_span) // RESIDUAL_MIX_GAMES]
        else:
            residual = pooled[next_below(pooled_size)]
        scores.append(max(0, prepared.base_cents[index] + residual))
    return scores


def _tally(
    prepared: _Prepared,
    vp: list[int],
    wins: list[int],
    points_for: list[int],
    counts: list[list[int]],
) -> None:
    """Rank one simulated season, build the seeded field, and increment the team counters.

    Division winners are seeds 1..D in the normal VP/wins/points-for order, followed by the
    remaining teams in that same order. The top ``bye_count`` seeds (always division winners) get a
    bye, and the top ``playoff_field`` seeds qualify. Team name and then team id break a full
    numeric tie so seeds stay distinct; ``rank_teams`` shares a rank in that case.
    """
    order = sorted(
        range(len(prepared.team_ids)),
        key=lambda index: (
            -vp[index],
            -wins[index],
            -points_for[index],
            prepared.team_names[index],
            prepared.team_ids[index],
        ),
    )
    seen_divisions: set[str] = set()
    winners: list[int] = []
    for index in order:
        division = prepared.divisions[index]
        if division in seen_divisions:
            continue
        seen_divisions.add(division)
        winners.append(index)

    winner_set = set(winners)
    for position, index in enumerate(winners):
        counts[index][0] += 1
        counts[index][2] += 1
        if position < prepared.bye_count:
            counts[index][1] += 1

    remaining_slots = prepared.playoff_field - len(winners)
    for index in order:
        if remaining_slots == 0:
            break
        if index in winner_set:
            continue
        counts[index][0] += 1
        remaining_slots -= 1


def _result(prepared: _Prepared, counts: list[list[int]], *, iterations: int) -> SeasonSimulation:
    """Project the mutable counters into the immutable per-team result."""
    return SeasonSimulation(
        iterations=iterations,
        teams=tuple(
            TeamPredictionCounts(
                team_id=team_id,
                team_name=team_name,
                division=division,
                playoff_count=playoff_count,
                bye_count=bye_count,
                division_title_count=division_title_count,
            )
            for (
                team_id,
                team_name,
                division,
                (playoff_count, bye_count, division_title_count),
            ) in zip(
                prepared.team_ids,
                prepared.team_names,
                prepared.divisions,
                counts,
                strict=True,
            )
        ),
        completed_weeks=prepared.completed_weeks,
        remaining_weeks=tuple(week.week for week in prepared.weeks),
        playoff_field=prepared.playoff_field,
        division_count=prepared.division_count,
        bye_count=prepared.bye_count,
        confidence=prepared.confidence,
        scale=prepared.scale,
        base_points=prepared.base_points,
        observation_counts=prepared.observation_counts,
        uses_two_way_residuals=prepared.uses_two_way_residuals,
        pooled_residual_count=len(prepared.pooled_residuals),
    )


def _bye_count(playoff_field: int, division_count: int) -> int:
    """Derive the first-round bye count from the playoff bracket, capped at the divisions.

    A bracket of the next power of two above the field leaves the difference as byes. Only division
    winners can receive one, so the count can never exceed the number of divisions.
    """
    bracket_size = 1 << (playoff_field - 1).bit_length()
    return min(division_count, max(0, bracket_size - playoff_field))


def _tick_scale(team_ids: tuple[int, ...], teams: tuple[TeamSeasonTotals, ...]) -> int:
    """Return a common denominator for every possible tie split and every current VP total.

    ``LCM(1..T, 2)`` makes every group-size split exact. Extending it with the current VP
    denominators keeps a stored total convertible to ticks even if it came from a different
    season shape.
    """
    scale = lcm(*range(1, len(team_ids) + 1), 2)
    for team in teams:
        scale = lcm(scale, team.vp.denominator)
    return scale


def _vp_ticks(vp: Fraction, scale: int) -> int:
    """Convert an exact season VP total to integer ticks on ``scale``."""
    scaled = vp * scale
    assert scaled.denominator == 1, "the tick scale must cover every current VP denominator"
    return scaled.numerator


def _cents(value: Decimal) -> int:
    """Convert a two-decimal point value to integer cents without binary floating point."""
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _points(cents: int) -> Decimal:
    """Render diagnostic integer cents as an exact two-decimal point value."""
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _round_half_up(value: Fraction) -> int:
    """Round an exact fraction to the nearest integer, with halves away from zero."""
    if value >= 0:
        return (value.numerator * 2 + value.denominator) // (value.denominator * 2)
    return -_round_half_up(-value)
