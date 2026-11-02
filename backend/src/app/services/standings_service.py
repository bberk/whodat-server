"""Read-only standings and VP history queries over synchronized league data.

The service turns persisted league, team, matchup, and score rows into the data described by
ARCHITECTURE.md section 8. It never trusts the rounded ``score.victory_points`` columns:
weekly VP is recomputed from the stored scores with :func:`compute_week_vp` so season totals
and cumulative series stay exact (``Fraction``), and points for stay exact (``Decimal``).

Only completed regular-season weeks contribute. A week counts when it has stored matchups, all
of them are complete, none is a playoff matchup, and the week is within the ``league_season``
row's stored ``regular_season_length``. Playoff and incomplete weeks contribute no VP, no
W-L-T record, and no points for.

The service is transaction-neutral: it only reads and never commits, flushes, or rolls back.
The caller owns the session and its transaction.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import League, LeagueSeason, Matchup, Owner, Score, Team
from app.db.repositories import SyncRepository
from app.domain.clinch import (
    ClinchMatchup,
    ClinchStatus,
    ClinchTeam,
    compute_clinch_statuses,
)
from app.domain.predictions import (
    CountedScore,
    CountedWeek,
    FixedWeek,
    RemainingMatchup,
    RemainingWeek,
    TeamSeasonTotals,
)
from app.domain.standings import SeasonRow, rank_teams
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp
from app.domain.wapdate import (
    PERIODS,
    PeriodWindow,
    TeamPeriodStats,
    WapdateRow,
    build_wapdate_rows,
    offered_periods,
)


class StandingsServiceError(Exception):
    """Base class for errors raised when stored data cannot produce standings."""


class LeagueNotFoundError(StandingsServiceError, LookupError):
    """Raised when no league is stored for the requested id."""

    def __init__(self, league_id: int) -> None:
        self.league_id = league_id
        super().__init__(f"League {league_id} is not stored")


class SeasonNotFoundError(StandingsServiceError, LookupError):
    """Raised when the league exists but the requested season does not."""

    def __init__(self, league_id: int, season: int) -> None:
        self.league_id = league_id
        self.season = season
        super().__init__(f"League {league_id} has no stored season {season}")


class SeasonNotCurrentError(StandingsServiceError):
    """Raised when a stored season is not the league's latest stored season.

    Playoff odds estimate the rest of the season in progress, so an older stored season has no
    meaningful remaining schedule to simulate. The message never includes simulation data.
    """

    def __init__(self, league_id: int, season: int) -> None:
        self.league_id = league_id
        self.season = season
        super().__init__(f"League {league_id} season {season} is not the current season")


class SeasonSettingsError(StandingsServiceError):
    """Raised when a league season lacks the settings standings depend on."""

    def __init__(self, league_id: int, season: int, detail: str) -> None:
        self.league_id = league_id
        self.season = season
        self.detail = detail
        super().__init__(
            f"League {league_id}, season {season} has invalid season settings: {detail}"
        )


class TeamDataError(StandingsServiceError):
    """Raised when team, matchup, or score data for a season is missing or inconsistent."""

    def __init__(self, league_id: int, season: int, detail: str) -> None:
        self.league_id = league_id
        self.season = season
        self.detail = detail
        super().__init__(
            f"Team data for league {league_id}, season {season} is incomplete: {detail}"
        )


@dataclass(frozen=True)
class StandingRow:
    """One team's overall standing, including its per-week VP for counted weeks.

    ``victory_points`` is the exact sum of ``weekly_vp`` as a Fraction. ``points_for`` is the
    exact sum of stored scores as a Decimal. The API layer serializes both as strings.
    ``final_standing`` is the provider-reported final position including playoffs (1 = champion),
    or ``None`` while the provider has not reported one.
    """

    rank: int
    team_id: int
    team_name: str
    owner_name: str | None
    division: str | None
    victory_points: Fraction
    wins: int
    losses: int
    ties: int
    points_for: Decimal
    weekly_vp: tuple[Fraction, ...]
    clinch: ClinchStatus | None
    final_standing: int | None


@dataclass(frozen=True)
class DivisionStandings:
    """A division's rows in overall-rank order.

    ``name`` is ``None`` for teams without a division; that group sorts after named divisions.
    Rows are the same objects as the overall standings and keep their overall league rank.
    """

    name: str | None
    standings: tuple[StandingRow, ...]


type ProjectionReason = Literal[
    "no_active_week",
    "projections_not_synced",
    "projections_incomplete",
    "incomplete_schedule",
]


@dataclass(frozen=True)
class ProjectedTeamWeek:
    """One team's provider-projected points and the VP and record they would earn."""

    team_id: int
    opponent_team_id: int | None
    points: Decimal
    victory_points: Fraction
    wins: int
    losses: int
    ties: int


@dataclass(frozen=True)
class Projection:
    """The active week's provider projection, or why the projected view is unavailable.

    A ``week`` means the projection is applied: the standings, chart, WAPDate, clinch, and odds
    treat the week as played with these scores. ``reason`` is set only when ``week`` is ``None``.
    ``as_of`` is the last successful projection fetch for the season, never the request time.
    """

    week: int | None
    reason: ProjectionReason | None
    as_of: datetime | None
    is_cup_week: bool
    teams: tuple[ProjectedTeamWeek, ...]

    @property
    def applied(self) -> bool:
        """Return whether this projection can be included in a read."""
        return self.week is not None


@dataclass(frozen=True)
class Standings:
    """Overall and per-division standings for one league season."""

    league_id: int
    season: int
    completed_weeks: int
    overall: tuple[StandingRow, ...]
    divisions: tuple[DivisionStandings, ...]
    #: The weeks that ``weekly_vp`` aligns to. It equals the completed weeks, plus the projected
    #: week when the projected view is applied.
    weeks: tuple[int, ...] = ()
    #: The active week even when no projected read was requested, so a client can enable or
    #: disable its switch without a second request. ``None`` means the season has no active week.
    active_week: int | None = None
    #: Present only when the caller asked for the projected view; ``None`` otherwise.
    projection: Projection | None = None


@dataclass(frozen=True)
class TeamVpHistory:
    """One team's exact weekly VP and cumulative VP through each counted week."""

    team_id: int
    team_name: str
    weekly: tuple[Fraction, ...]
    cumulative: tuple[Fraction, ...]


@dataclass(frozen=True)
class VpHistory:
    """Completed regular-season weeks and every team's weekly/cumulative VP series."""

    weeks: tuple[int, ...]
    teams: tuple[TeamVpHistory, ...]
    #: Weeks in ``weeks`` that came from the active week's provider projection.
    projected_weeks: tuple[int, ...] = ()
    active_week: int | None = None
    projection: Projection | None = None


@dataclass(frozen=True)
class WapdatePeriod:
    """One offered WAPDate period with its lowest-first rows."""

    period: int
    start_week: int
    end_week: int
    status: Literal["complete", "current"]
    weeks: tuple[int, ...]
    rows: tuple[WapdateRow, ...]


@dataclass(frozen=True)
class Wapdate:
    """The offered WAPDate periods for one league season."""

    league_id: int
    season: int
    highest_completed_week: int | None
    periods: tuple[WapdatePeriod, ...]
    projected_week: int | None = None
    projection: Projection | None = None


@dataclass(frozen=True)
class PredictionSnapshot:
    """The exact inputs the pure playoff simulator needs for one league season.

    Current totals come from :meth:`StandingsService._aggregate`, so the simulation and the
    standings page agree about the past. ``counted_weeks`` carries the raw scores used to estimate
    the score model, and ``remaining_weeks`` lists every regular-season week that is not counted,
    including a week with no stored schedule (the simulator reports it as incomplete).
    """

    league_id: int
    season: int
    regular_season_length: int
    cup_week: int | None
    playoff_team_count: int | None
    teams: tuple[TeamSeasonTotals, ...]
    counted_weeks: tuple[CountedWeek, ...]
    remaining_weeks: tuple[RemainingWeek, ...]
    #: The active week whose provider projection is fixed into the simulation, or ``None``.
    projected_week: int | None = None
    #: The deterministic projected week passed to the simulator, excluded from ``remaining_weeks``.
    fixed_weeks: tuple[FixedWeek, ...] = ()
    #: Why the projected view is unavailable when ``projected_week`` is ``None``.
    projection: Projection | None = None


@dataclass(frozen=True)
class _SeasonContext:
    """Validated league season data shared by the public read methods."""

    league_id: int
    season: int
    regular_season_length: int
    cup_week: int | None
    playoff_team_count: int | None
    teams: tuple[Team, ...]
    owner_names: Mapping[int, str]


@dataclass(frozen=True)
class _SeasonAggregate:
    """Exact per-team aggregates over the counted weeks."""

    season_vp: Mapping[int, Fraction]
    wins: Mapping[int, int]
    losses: Mapping[int, int]
    ties: Mapping[int, int]
    points_for: Mapping[int, Decimal]
    weekly_vp: Mapping[int, tuple[Fraction, ...]]


def _cumulative(values: Sequence[Fraction]) -> tuple[Fraction, ...]:
    """Return running exact sums, so cumulative[W] = sum(weekly[0..W])."""
    total = Fraction(0)
    result: list[Fraction] = []
    for value in values:
        total += value
        result.append(total)
    return tuple(result)


class StandingsService:
    """Produce overall standings, division groups, and VP history for a stored season.

    The caller owns the SQLAlchemy session. Reads never commit; the service is safe to use
    inside a larger read transaction and raises a typed error instead of returning partial data.
    """

    def __init__(self, session: Session) -> None:
        """Bind the service to a caller-owned session."""
        self._session = session
        self._repository = SyncRepository(session)

    def get_standings(
        self, league_id: int, season: int, *, include_projected: bool = False
    ) -> Standings:
        """Return overall standings plus divisions that group the same overall-ranked rows.

        Division rows are the same :class:`StandingRow` objects as ``overall`` and therefore
        carry the team's overall league rank (AC-ST-06). Divisions are ordered alphabetically
        by name, with the no-division group last. With no completed regular-season weeks the
        result has no rows, no divisions, and ``completed_weeks == 0``.

        ``include_projected`` adds the active week's stored provider projection as a played week:
        its VP, W/L/T, and points for are included, ``weeks`` and ``weekly_vp`` gain the week, and
        clinch designations are recomputed from the projected totals with that week removed from
        the remaining schedule. ``active_week`` is always reported so a client can offer the
        switch without a projected request. A missing or incomplete projection never partially
        fills a week; ``projection.reason`` explains why it was not applied.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        active_week, projection = self._projection(context, include_projected)
        applied = projection if projection is not None and projection.applied else None
        if not weeks and applied is None:
            return Standings(
                league_id=league_id,
                season=season,
                completed_weeks=0,
                overall=(),
                divisions=(),
                weeks=(),
                active_week=active_week,
                projection=projection,
            )

        aggregate = self._aggregate(context, weeks, projection=applied)
        clinch = self._clinch_statuses(context, weeks, aggregate, projection=applied)
        teams_by_id = {team.id: team for team in context.teams}
        season_rows = self._season_rows(context, aggregate)

        overall: list[StandingRow] = []
        for ranked in rank_teams(season_rows):
            team = teams_by_id[ranked.team_id]
            owner_name = (
                context.owner_names.get(team.owner_id) if team.owner_id is not None else None
            )
            overall.append(
                StandingRow(
                    rank=ranked.rank,
                    team_id=ranked.team_id,
                    team_name=ranked.team_name,
                    owner_name=owner_name,
                    division=ranked.division,
                    victory_points=ranked.vp,
                    wins=aggregate.wins[ranked.team_id],
                    losses=aggregate.losses[ranked.team_id],
                    ties=aggregate.ties[ranked.team_id],
                    points_for=ranked.points_for,
                    weekly_vp=aggregate.weekly_vp[ranked.team_id],
                    clinch=clinch[ranked.team_id],
                    final_standing=team.final_standing,
                )
            )

        display_weeks = weeks
        if applied is not None and applied.week is not None:
            display_weeks = weeks + (applied.week,)
        return Standings(
            league_id=league_id,
            season=season,
            completed_weeks=len(weeks),
            overall=tuple(overall),
            divisions=self._group_divisions(overall),
            weeks=display_weeks,
            active_week=active_week,
            projection=projection,
        )

    def get_last_place_team_ids(self, league_id: int, season: int) -> tuple[int, ...]:
        """Return the team id(s) ranked last by regular-season VP and the usual tiebreakers.

        The ranking is the same one the standings table uses: season VP, then head-to-head wins,
        then points for, with fully equal teams sharing a rank. Every team at the highest (worst)
        rank is returned, so a genuine tie for last place counts for each tied team rather than
        being broken arbitrarily.

        A last-place finish exists only once the whole regular season is stored and complete, so
        a season in progress (or one with a missing/incomplete week) returns an empty tuple rather
        than awarding the record early. This never looks at playoff results, which earn no VP.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        if len(weeks) < context.regular_season_length:
            return ()

        aggregate = self._aggregate(context, weeks)
        ranked = rank_teams(self._season_rows(context, aggregate))
        last_rank = max(row.rank for row in ranked)
        return tuple(sorted(row.team_id for row in ranked if row.rank == last_rank))

    def get_last_place_team_ids_for_seasons(
        self, league_id: int, seasons: Sequence[int]
    ) -> Mapping[int, tuple[int, ...]]:
        """Return last-place team ids for several seasons after loading stored rows once.

        This is the bulk form of :meth:`get_last_place_team_ids` for callers such as the History
        service that read many seasons in one request: it loads the league's seasons, teams,
        matchups, and scores once and then groups them in memory, instead of issuing three
        queries per week per season. Seasons whose settings or stored scores cannot produce a
        ranking are omitted (treated as "no last place"), so one bad season never fails a
        multi-season read. The same completed-regular-season, VP, H2H-win, and points-for rules
        apply as in the single-season method.
        """
        if self._session.get(League, league_id) is None:
            raise LeagueNotFoundError(league_id)

        requested = set(seasons)
        season_rows = {row.season: row for row in self._repository.list_league_seasons(league_id)}
        teams_by_season: dict[int, list[Team]] = {}
        for team in self._repository.list_teams(league_id):
            teams_by_season.setdefault(team.season, []).append(team)
        matchups_by_week: dict[tuple[int, int], list[Matchup]] = {}
        for matchup in self._repository.list_matchups(league_id):
            matchups_by_week.setdefault((matchup.season, matchup.week), []).append(matchup)
        scores_by_week: dict[tuple[int, int], list[Score]] = {}
        for score in self._repository.list_scores(league_id):
            scores_by_week.setdefault((score.season, score.week), []).append(score)

        result: dict[int, tuple[int, ...]] = {}
        for season in sorted(requested):
            league_season = season_rows.get(season)
            if league_season is None:
                continue
            try:
                regular_season_length = self._regular_season_length(league_season)
            except SeasonSettingsError:
                continue
            season_teams = tuple(teams_by_season.get(season, ()))
            if not season_teams:
                continue

            context = _SeasonContext(
                league_id=league_id,
                season=season,
                regular_season_length=regular_season_length,
                cup_week=league_season.cup_week,
                playoff_team_count=None,
                teams=season_teams,
                owner_names={},
            )
            weeks: list[int] = []
            for week in range(1, regular_season_length + 1):
                matchups = matchups_by_week.get((season, week), ())
                if not matchups:
                    continue
                if any(matchup.is_playoff or not matchup.is_complete for matchup in matchups):
                    continue
                weeks.append(week)
            if len(weeks) < regular_season_length:
                result[season] = ()
                continue

            def matchups_for(week: int, current_season: int = season) -> Sequence[Matchup]:
                return matchups_by_week.get((current_season, week), ())

            def scores_for(week: int, current_season: int = season) -> Sequence[Score]:
                return scores_by_week.get((current_season, week), ())

            try:
                aggregate = self._aggregate_from(context, weeks, matchups_for, scores_for)
            except TeamDataError:
                result[season] = ()
                continue
            ranked = rank_teams(self._season_rows(context, aggregate))
            last_rank = max(row.rank for row in ranked)
            result[season] = tuple(sorted(row.team_id for row in ranked if row.rank == last_rank))

        return result

    def get_vp_history(
        self, league_id: int, season: int, *, include_projected: bool = False
    ) -> VpHistory:
        """Return counted weeks plus each team's exact weekly and cumulative VP series.

        Teams are ordered by id for a stable chart legend. With no completed regular-season
        weeks and no applied projection both ``weeks`` and ``teams`` are empty. When the projected
        view is applied, the active week is appended to ``weeks`` and every series, and
        ``projected_weeks`` marks it so the chart can draw a distinct projected segment.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        active_week, projection = self._projection(context, include_projected)
        applied = projection if projection is not None and projection.applied else None
        if not weeks and applied is None:
            return VpHistory(
                weeks=(),
                teams=(),
                active_week=active_week,
                projection=projection,
            )

        aggregate = self._aggregate(context, weeks, projection=applied)
        teams = tuple(
            TeamVpHistory(
                team_id=team.id,
                team_name=team.name,
                weekly=aggregate.weekly_vp[team.id],
                cumulative=_cumulative(aggregate.weekly_vp[team.id]),
            )
            for team in sorted(context.teams, key=lambda stored_team: stored_team.id)
        )
        display_weeks = weeks
        projected_weeks: tuple[int, ...] = ()
        if applied is not None and applied.week is not None:
            display_weeks = weeks + (applied.week,)
            projected_weeks = (applied.week,)
        return VpHistory(
            weeks=display_weeks,
            teams=teams,
            projected_weeks=projected_weeks,
            active_week=active_week,
            projection=projection,
        )

    def get_wapdate(
        self, league_id: int, season: int, *, include_projected: bool = False
    ) -> Wapdate:
        """Return the offered WAPDate periods with lowest-first rows.

        Periods are fixed and independent: weeks 1-4, 5-8 and 9-12 only, with no VP, wins, or
        points for carried between them. Each period's totals come from the same weekly engine
        the standings use, so a cup week keeps its cup-week VP and points for while adding no
        wins. Only offered periods are returned; with no completed regular-season weeks the
        result has no periods.

        With ``include_projected`` the active week joins the period that contains it (weeks 13
        and later belong to no period). The period's safe-from-last bound treats the projected
        week as played, so its remaining-week count starts the week after it.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        highest = weeks[-1] if weeks else None
        _, projection = self._projection(context, include_projected)
        applied = projection if projection is not None and projection.applied else None

        windows = list(offered_periods(weeks))
        if applied is not None and applied.week is not None:
            period = next(
                (
                    candidate
                    for candidate in PERIODS
                    if candidate.start_week <= applied.week <= candidate.end_week
                ),
                None,
            )
            if period is not None and all(
                window.period.number != period.number for window in windows
            ):
                # The projected week can be the first week of a new period before any of that
                # period's weeks is complete. Offer it as current with no completed weeks; the
                # loop below adds the projected week to its totals.
                windows.append(PeriodWindow(period=period, status="current", weeks=()))
        windows.sort(key=lambda window: window.period.number)

        periods: list[WapdatePeriod] = []
        for window in windows:
            in_period_week: int | None = None
            if (
                applied is not None
                and applied.week is not None
                and window.period.start_week <= applied.week <= window.period.end_week
            ):
                in_period_week = applied.week
            period_projection = applied if in_period_week is not None else None
            aggregate = self._aggregate(context, window.weeks, projection=period_projection)
            stats = tuple(
                TeamPeriodStats(
                    team_id=team.id,
                    team_name=team.name,
                    vp=aggregate.season_vp[team.id],
                    wins=aggregate.wins[team.id],
                    points_for=aggregate.points_for[team.id],
                )
                for team in context.teams
            )
            effective_highest = in_period_week if in_period_week is not None else highest
            rows = build_wapdate_rows(
                stats,
                window,
                highest_completed_week=effective_highest,
                cup_week=context.cup_week,
            )
            period_weeks = window.weeks
            if in_period_week is not None:
                period_weeks = window.weeks + (in_period_week,)
            periods.append(
                WapdatePeriod(
                    period=window.period.number,
                    start_week=window.period.start_week,
                    end_week=window.period.end_week,
                    status=window.status,
                    weeks=period_weeks,
                    rows=rows,
                )
            )

        return Wapdate(
            league_id=league_id,
            season=season,
            highest_completed_week=highest,
            periods=tuple(periods),
            projected_week=applied.week if applied is not None else None,
            projection=projection,
        )

    def require_current_season(self, league_id: int, season: int) -> None:
        """Reject a stored season that is not the league's latest stored season.

        The "current season" is the maximum stored ``league_season.season`` for the league, the
        same rule the league refresh and the frontend's latest-season default use. An unknown
        league and an unstored season raise the same errors as every other read, so the response
        does not distinguish them; an older stored season raises
        :class:`SeasonNotCurrentError` before any simulation input is read.
        """
        if self._session.get(League, league_id) is None:
            raise LeagueNotFoundError(league_id)
        if self._repository.get_league_season(league_id, season) is None:
            raise SeasonNotFoundError(league_id, season)
        latest = max(row.season for row in self._repository.list_league_seasons(league_id))
        if season != latest:
            raise SeasonNotCurrentError(league_id, season)

    def get_prediction_snapshot(
        self, league_id: int, season: int, *, include_projected: bool = False
    ) -> PredictionSnapshot:
        """Return current exact totals, counted raw scores, and every remaining pairing.

        The current totals reuse the same completed-week definition and aggregation as
        :meth:`get_standings`. An invalid cup week is a season-settings fault and raises
        :class:`SeasonSettingsError`; a missing playoff field is left as ``None`` so the simulator
        can return its documented unavailable reason instead of a guessed field size.

        With ``include_projected`` the active week's provider projection becomes a
        :class:`~app.domain.predictions.FixedWeek`: it is applied deterministically by the
        simulator and removed from ``remaining_weeks``. It is never added to ``counted_weeks``, so
        the estimated team strength is unchanged. ``teams`` therefore stays the actual current
        total and the simulation applies the projected week exactly once.
        """
        context = self._load_context(league_id, season)
        if context.cup_week is not None and (
            isinstance(context.cup_week, bool)
            or not 1 <= context.cup_week <= context.regular_season_length
        ):
            raise SeasonSettingsError(
                league_id,
                season,
                "cup_week must be between 1 and the regular-season length",
            )

        weeks = self._completed_weeks(context)
        aggregate = self._aggregate(context, weeks) if weeks else None
        _, projection = self._projection(context, include_projected)
        applied = projection if projection is not None and projection.applied else None

        teams = tuple(
            TeamSeasonTotals(
                team_id=team.id,
                team_name=team.name,
                division=team.division,
                vp=aggregate.season_vp[team.id] if aggregate is not None else Fraction(0),
                wins=aggregate.wins[team.id] if aggregate is not None else 0,
                points_for=aggregate.points_for[team.id] if aggregate is not None else Decimal(0),
            )
            for team in context.teams
        )
        counted = tuple(
            CountedWeek(
                week=week,
                scores=tuple(
                    CountedScore(team_id=score.team_id, points=score.points)
                    for score in self._repository.get_week_scores(
                        context.league_id, context.season, week
                    )
                ),
            )
            for week in weeks
        )
        completed = frozenset(weeks)
        fixed_weeks: list[FixedWeek] = []
        remaining_weeks: list[RemainingWeek] = []
        for week in range(1, context.regular_season_length + 1):
            if week in completed:
                continue
            matchups = self._repository.get_week_matchups(context.league_id, context.season, week)
            if applied is not None and week == applied.week:
                fixed_weeks.append(
                    FixedWeek(
                        week=week,
                        scores=tuple(
                            CountedScore(team_id=team.team_id, points=team.points)
                            for team in applied.teams
                        ),
                        matchups=tuple(
                            RemainingMatchup(
                                home_team_id=matchup.home_team_id,
                                away_team_id=matchup.away_team_id,
                            )
                            for matchup in matchups
                        ),
                    )
                )
                continue
            remaining_weeks.append(
                RemainingWeek(
                    week=week,
                    matchups=tuple(
                        RemainingMatchup(
                            home_team_id=matchup.home_team_id,
                            away_team_id=matchup.away_team_id,
                        )
                        for matchup in matchups
                    ),
                    is_playoff=any(matchup.is_playoff for matchup in matchups),
                )
            )
        return PredictionSnapshot(
            league_id=league_id,
            season=season,
            regular_season_length=context.regular_season_length,
            cup_week=context.cup_week,
            playoff_team_count=context.playoff_team_count,
            teams=teams,
            counted_weeks=counted,
            remaining_weeks=tuple(remaining_weeks),
            projected_week=applied.week if applied is not None else None,
            fixed_weeks=tuple(fixed_weeks),
            projection=projection,
        )

    def _active_week(self, context: _SeasonContext) -> tuple[int | None, ProjectionReason | None]:
        """Return the first incomplete week and an incomplete-schedule reason, if any.

        Every regular-season week must have a stored schedule and none may be a playoff week. The
        scan continues after the first incomplete week so a missing or playoff-marked later week
        is reported as an incomplete schedule, not as a finished season.
        """
        active: int | None = None
        for week in range(1, context.regular_season_length + 1):
            matchups = self._repository.get_week_matchups(context.league_id, context.season, week)
            if not matchups or any(matchup.is_playoff for matchup in matchups):
                return None, "incomplete_schedule"
            if active is None and any(not matchup.is_complete for matchup in matchups):
                active = week
        return active, None

    def _projection(
        self, context: _SeasonContext, include_projected: bool
    ) -> tuple[int | None, Projection | None]:
        """Return the active week and, when requested, its applied provider projection.

        The result is ``(active_week, None)`` for an ordinary read: the active week is still
        reported so a client can enable its switch. With ``include_projected`` the projection is
        computed from stored ``projected_score`` rows and the real VP engine. Any missing team,
        missing row, or non-regular-season schedule returns an explicit reason and no partial
        week.
        """
        active, schedule_reason = self._active_week(context)
        if not include_projected:
            return active, None

        league_season = self._repository.get_league_season(context.league_id, context.season)
        as_of = league_season.projections_refreshed_at if league_season is not None else None
        if schedule_reason is not None:
            return active, Projection(
                week=None,
                reason=schedule_reason,
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )
        if active is None:
            return None, Projection(
                week=None,
                reason="no_active_week",
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )

        # A completed week after the first incomplete one is a schedule gap. Appending the
        # projected week at the end of the series would then misalign it with its week number.
        completed = self._completed_weeks(context)
        if completed and active < completed[-1]:
            return active, Projection(
                week=None,
                reason="incomplete_schedule",
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )

        matchups = self._repository.get_week_matchups(context.league_id, context.season, active)
        if not matchups or any(matchup.is_playoff for matchup in matchups):
            return active, Projection(
                week=None,
                reason="incomplete_schedule",
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )

        roster_ids = {team.id for team in context.teams}
        participants: list[int] = []
        for matchup in matchups:
            participants.append(matchup.home_team_id)
            if matchup.away_team_id is not None:
                participants.append(matchup.away_team_id)
        if len(participants) != len(set(participants)) or set(participants) != roster_ids:
            return active, Projection(
                week=None,
                reason="incomplete_schedule",
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )

        projection_rows = self._repository.get_week_projections(
            context.league_id, context.season, active
        )
        points_by_team = {row.team_id: row.points for row in projection_rows}
        if not roster_ids.issubset(points_by_team):
            reason: ProjectionReason = (
                "projections_not_synced" if not projection_rows else "projections_incomplete"
            )
            return active, Projection(
                week=None,
                reason=reason,
                as_of=as_of,
                is_cup_week=False,
                teams=(),
            )

        opponent_by_team: dict[int, int | None] = {}
        for matchup in matchups:
            opponent_by_team[matchup.home_team_id] = matchup.away_team_id
            if matchup.away_team_id is not None:
                opponent_by_team[matchup.away_team_id] = matchup.home_team_id

        is_cup_week = context.cup_week == active
        team_weeks = [
            TeamWeek(
                team_id=team_id,
                points=points_by_team[team_id],
                opponent_id=opponent_by_team.get(team_id),
            )
            for team_id in sorted(roster_ids)
        ]
        week_values = compute_week_vp(team_weeks, h2h=not is_cup_week)

        wins = {team_id: 0 for team_id in roster_ids}
        losses = {team_id: 0 for team_id in roster_ids}
        ties = {team_id: 0 for team_id in roster_ids}
        if not is_cup_week:
            for matchup in matchups:
                away_id = matchup.away_team_id
                if away_id is None:
                    continue
                home_points = points_by_team[matchup.home_team_id]
                away_points = points_by_team[away_id]
                if home_points > away_points:
                    wins[matchup.home_team_id] += 1
                    losses[away_id] += 1
                elif home_points < away_points:
                    losses[matchup.home_team_id] += 1
                    wins[away_id] += 1
                else:
                    ties[matchup.home_team_id] += 1
                    ties[away_id] += 1

        teams = tuple(
            ProjectedTeamWeek(
                team_id=team_id,
                opponent_team_id=opponent_by_team.get(team_id),
                points=points_by_team[team_id],
                victory_points=week_values[team_id].total,
                wins=wins[team_id],
                losses=losses[team_id],
                ties=ties[team_id],
            )
            for team_id in sorted(roster_ids)
        )
        return active, Projection(
            week=active,
            reason=None,
            as_of=as_of,
            is_cup_week=is_cup_week,
            teams=teams,
        )

    def _load_context(self, league_id: int, season: int) -> _SeasonContext:
        """Validate the league, league season, settings, teams, and owners."""
        if self._session.get(League, league_id) is None:
            raise LeagueNotFoundError(league_id)

        league_season = self._repository.get_league_season(league_id, season)
        if league_season is None:
            raise SeasonNotFoundError(league_id, season)

        regular_season_length = self._regular_season_length(league_season)
        teams = tuple(self._repository.get_teams(league_id, season))
        if not teams:
            raise TeamDataError(league_id, season, "no teams are stored for this season")

        owner_ids = {team.owner_id for team in teams if team.owner_id is not None}
        owner_names: dict[int, str] = {}
        if owner_ids:
            owners = self._session.scalars(select(Owner).where(Owner.id.in_(owner_ids))).all()
            owner_names = {owner.id: owner.display_name for owner in owners}

        return _SeasonContext(
            league_id=league_id,
            season=season,
            regular_season_length=regular_season_length,
            cup_week=league_season.cup_week,
            playoff_team_count=self._playoff_team_count(league_season),
            teams=teams,
            owner_names=owner_names,
        )

    @staticmethod
    def _playoff_team_count(league_season: LeagueSeason) -> int | None:
        """Return the stored playoff field size, or None when it is absent or unusable."""
        raw: object = league_season.league_season_metadata.get("playoff_team_count")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            return None
        return raw

    def _clinch_statuses(
        self,
        context: _SeasonContext,
        completed_weeks: Sequence[int],
        aggregate: _SeasonAggregate,
        projection: Projection | None = None,
    ) -> dict[int, ClinchStatus | None]:
        """Compute proven designations from exact totals and every stored future pairing.

        A regular-season week flagged as a playoff week is inconsistent stored data, so no team
        receives a designation. Missing future weeks are rejected by the pure calculator rather
        than filled from current standings. When a projection is applied, its week is treated as
        already played: it is removed from the remaining matchups and added to the completed
        weeks, so the conservative search does not count it twice.
        """
        remaining_matchups: list[ClinchMatchup] = []
        completed = frozenset(completed_weeks)
        projected_week = projection.week if projection is not None else None
        for week in range(1, context.regular_season_length + 1):
            if week in completed or week == projected_week:
                continue
            for matchup in self._repository.get_week_matchups(
                context.league_id, context.season, week
            ):
                if matchup.is_playoff:
                    return {team.id: None for team in context.teams}
                remaining_matchups.append(
                    ClinchMatchup(
                        week=matchup.week,
                        home_team_id=matchup.home_team_id,
                        away_team_id=matchup.away_team_id,
                    )
                )

        effective_completed = tuple(completed_weeks) + (
            (projected_week,) if projected_week is not None else ()
        )
        return compute_clinch_statuses(
            [
                ClinchTeam(
                    team_id=team.id,
                    vp=aggregate.season_vp[team.id],
                    wins=aggregate.wins[team.id],
                    division=team.division,
                )
                for team in context.teams
            ],
            remaining_matchups,
            completed_weeks=effective_completed,
            regular_season_length=context.regular_season_length,
            playoff_team_count=context.playoff_team_count,
            cup_week=context.cup_week,
        )

    def _regular_season_length(self, league_season: LeagueSeason) -> int:
        """Read and validate the season's stored regular-season length."""
        raw: object = league_season.league_season_metadata.get("regular_season_length")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise SeasonSettingsError(
                league_season.league_id,
                league_season.season,
                "regular_season_length must be a positive integer",
            )
        return raw

    def _completed_weeks(self, context: _SeasonContext) -> tuple[int, ...]:
        """Return the completed regular-season week numbers within the stored season bound."""
        weeks: list[int] = []
        for week in range(1, context.regular_season_length + 1):
            matchups = self._repository.get_week_matchups(context.league_id, context.season, week)
            if not matchups:
                continue
            if any(matchup.is_playoff or not matchup.is_complete for matchup in matchups):
                continue
            weeks.append(week)
        return tuple(weeks)

    def _aggregate(
        self,
        context: _SeasonContext,
        weeks: Sequence[int],
        *,
        projection: Projection | None = None,
    ) -> _SeasonAggregate:
        """Aggregate a season's counted weeks by loading each week from the repository."""
        return self._aggregate_from(
            context,
            weeks,
            lambda week: self._repository.get_week_matchups(
                context.league_id, context.season, week
            ),
            lambda week: self._repository.get_week_scores(context.league_id, context.season, week),
            projection=projection,
        )

    @staticmethod
    def _aggregate_from(
        context: _SeasonContext,
        weeks: Sequence[int],
        matchups_for: Callable[[int], Sequence[Matchup]],
        scores_for: Callable[[int], Sequence[Score]],
        *,
        projection: Projection | None = None,
    ) -> _SeasonAggregate:
        """Recompute weekly VP and W-L-T from caller-supplied week loaders.

        A cup week (``context.cup_week``) still counts for points for and its VP, but its
        matchups never change the W-L-T record and every team gets zero head-to-head VP. An
        applied projection is appended after the counted weeks, so its weekly VP aligns with the
        extra week in ``Standings.weeks`` and it contributes its own record and points for.
        """
        roster_ids = {team.id for team in context.teams}
        weekly_by_team: dict[int, list[Fraction]] = {team_id: [] for team_id in roster_ids}
        wins = {team_id: 0 for team_id in roster_ids}
        losses = {team_id: 0 for team_id in roster_ids}
        ties = {team_id: 0 for team_id in roster_ids}
        points_for = {team_id: Decimal(0) for team_id in roster_ids}

        for week in weeks:
            is_cup_week = week == context.cup_week
            matchups = matchups_for(week)
            scores = scores_for(week)
            scores_by_team = {score.team_id: score for score in scores}

            unknown_score_teams = set(scores_by_team) - roster_ids
            if unknown_score_teams:
                raise TeamDataError(
                    context.league_id,
                    context.season,
                    f"week {week} has scores for teams outside the season roster: "
                    f"{sorted(unknown_score_teams)}",
                )

            opponent_by_team: dict[int, int | None] = {}
            for matchup in matchups:
                for team_id in (matchup.home_team_id, matchup.away_team_id):
                    if team_id is not None and team_id not in roster_ids:
                        raise TeamDataError(
                            context.league_id,
                            context.season,
                            f"week {week} references team {team_id} outside the season roster",
                        )
                home_score = scores_by_team.get(matchup.home_team_id)
                if home_score is None:
                    raise TeamDataError(
                        context.league_id,
                        context.season,
                        f"week {week} is missing a score for team {matchup.home_team_id}",
                    )
                opponent_by_team[matchup.home_team_id] = matchup.away_team_id
                if matchup.away_team_id is not None:
                    away_score = scores_by_team.get(matchup.away_team_id)
                    if away_score is None:
                        raise TeamDataError(
                            context.league_id,
                            context.season,
                            f"week {week} is missing a score for team {matchup.away_team_id}",
                        )
                    opponent_by_team[matchup.away_team_id] = matchup.home_team_id

                    if not is_cup_week:
                        if home_score.points > away_score.points:
                            wins[matchup.home_team_id] += 1
                            losses[matchup.away_team_id] += 1
                        elif home_score.points < away_score.points:
                            losses[matchup.home_team_id] += 1
                            wins[matchup.away_team_id] += 1
                        else:
                            ties[matchup.home_team_id] += 1
                            ties[matchup.away_team_id] += 1

            for team_id, score in scores_by_team.items():
                points_for[team_id] += score.points

            team_weeks = [
                TeamWeek(
                    team_id=score.team_id,
                    points=score.points,
                    opponent_id=opponent_by_team.get(score.team_id),
                )
                for score in scores
            ]
            week_values = compute_week_vp(team_weeks, h2h=not is_cup_week)
            for team_id in roster_ids:
                week_vp = week_values.get(team_id)
                weekly_by_team[team_id].append(
                    week_vp.total if week_vp is not None else Fraction(0)
                )

        if projection is not None:
            for projected in projection.teams:
                if projected.team_id not in roster_ids:
                    raise TeamDataError(
                        context.league_id,
                        context.season,
                        f"projected week {projection.week} references a team outside the roster",
                    )
                weekly_by_team[projected.team_id].append(projected.victory_points)
                wins[projected.team_id] += projected.wins
                losses[projected.team_id] += projected.losses
                ties[projected.team_id] += projected.ties
                points_for[projected.team_id] += projected.points

        season_vp = {
            team_id: sum(series, Fraction(0)) for team_id, series in weekly_by_team.items()
        }
        weekly_series = {team_id: tuple(series) for team_id, series in weekly_by_team.items()}
        return _SeasonAggregate(
            season_vp=season_vp,
            wins=wins,
            losses=losses,
            ties=ties,
            points_for=points_for,
            weekly_vp=weekly_series,
        )

    @staticmethod
    def _season_rows(context: _SeasonContext, aggregate: _SeasonAggregate) -> list[SeasonRow]:
        """Build the ranking inputs for every team from exact regular-season totals."""
        return [
            SeasonRow(
                team_id=team.id,
                team_name=team.name,
                vp=aggregate.season_vp[team.id],
                h2h_wins=aggregate.wins[team.id],
                points_for=aggregate.points_for[team.id],
                division=team.division,
            )
            for team in context.teams
        ]

    @staticmethod
    def _group_divisions(overall: Sequence[StandingRow]) -> tuple[DivisionStandings, ...]:
        """Group already-ranked rows by division without ranking a division subset."""
        grouped: dict[str | None, list[StandingRow]] = {}
        for row in overall:
            grouped.setdefault(row.division, []).append(row)

        names = sorted(name for name in grouped if name is not None)
        divisions = [DivisionStandings(name=name, standings=tuple(grouped[name])) for name in names]
        if None in grouped:
            divisions.append(DivisionStandings(name=None, standings=tuple(grouped[None])))
        return tuple(divisions)
