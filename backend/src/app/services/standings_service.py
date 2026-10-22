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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import League, LeagueSeason, Owner, Team
from app.db.repositories import SyncRepository
from app.domain.standings import SeasonRow, rank_teams
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp


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


@dataclass(frozen=True)
class DivisionStandings:
    """A division's rows in overall-rank order.

    ``name`` is ``None`` for teams without a division; that group sorts after named divisions.
    Rows are the same objects as the overall standings and keep their overall league rank.
    """

    name: str | None
    standings: tuple[StandingRow, ...]


@dataclass(frozen=True)
class Standings:
    """Overall and per-division standings for one league season."""

    league_id: int
    season: int
    completed_weeks: int
    overall: tuple[StandingRow, ...]
    divisions: tuple[DivisionStandings, ...]


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


@dataclass(frozen=True)
class _SeasonContext:
    """Validated league season data shared by the public read methods."""

    league_id: int
    season: int
    regular_season_length: int
    cup_week: int | None
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

    def get_standings(self, league_id: int, season: int) -> Standings:
        """Return overall standings plus divisions that group the same overall-ranked rows.

        Division rows are the same :class:`StandingRow` objects as ``overall`` and therefore
        carry the team's overall league rank (AC-ST-06). Divisions are ordered alphabetically
        by name, with the no-division group last. With no completed regular-season weeks the
        result has no rows, no divisions, and ``completed_weeks == 0``.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        if not weeks:
            return Standings(
                league_id=league_id,
                season=season,
                completed_weeks=0,
                overall=(),
                divisions=(),
            )

        aggregate = self._aggregate(context, weeks)
        teams_by_id = {team.id: team for team in context.teams}
        season_rows = [
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
                )
            )

        return Standings(
            league_id=league_id,
            season=season,
            completed_weeks=len(weeks),
            overall=tuple(overall),
            divisions=self._group_divisions(overall),
        )

    def get_vp_history(self, league_id: int, season: int) -> VpHistory:
        """Return counted weeks plus each team's exact weekly and cumulative VP series.

        Teams are ordered by id for a stable chart legend. With no completed regular-season
        weeks both ``weeks`` and ``teams`` are empty.
        """
        context = self._load_context(league_id, season)
        weeks = self._completed_weeks(context)
        if not weeks:
            return VpHistory(weeks=(), teams=())

        aggregate = self._aggregate(context, weeks)
        teams = tuple(
            TeamVpHistory(
                team_id=team.id,
                team_name=team.name,
                weekly=aggregate.weekly_vp[team.id],
                cumulative=_cumulative(aggregate.weekly_vp[team.id]),
            )
            for team in sorted(context.teams, key=lambda stored_team: stored_team.id)
        )
        return VpHistory(weeks=weeks, teams=teams)

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
            teams=teams,
            owner_names=owner_names,
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

    def _aggregate(self, context: _SeasonContext, weeks: Sequence[int]) -> _SeasonAggregate:
        """Recompute weekly VP and W-L-T and accumulate exact season totals.

        A cup week (``context.cup_week``) still counts for points for and its VP, but its
        matchups never change the W-L-T record and every team gets zero head-to-head VP.
        """
        roster_ids = {team.id for team in context.teams}
        weekly_by_team: dict[int, list[Fraction]] = {team_id: [] for team_id in roster_ids}
        wins = {team_id: 0 for team_id in roster_ids}
        losses = {team_id: 0 for team_id in roster_ids}
        ties = {team_id: 0 for team_id in roster_ids}
        points_for = {team_id: Decimal(0) for team_id in roster_ids}

        for week in weeks:
            is_cup_week = week == context.cup_week
            matchups = self._repository.get_week_matchups(context.league_id, context.season, week)
            scores = self._repository.get_week_scores(context.league_id, context.season, week)
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
