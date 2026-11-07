"""Helper functions and data structures for projected week computations."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from app.db.models import Team
from app.db.repositories import SyncRepository
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp

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


def determine_active_week(
    repository: SyncRepository,
    league_id: int,
    season: int,
    regular_season_length: int,
) -> tuple[int | None, ProjectionReason | None]:
    """Return the first incomplete week and an incomplete-schedule reason, if any.

    Every regular-season week must have a stored schedule and none may be a playoff week. The
    scan continues after the first incomplete week so a missing or playoff-marked later week
    is reported as an incomplete schedule, not as a finished season.
    """
    active: int | None = None
    for week in range(1, regular_season_length + 1):
        matchups = repository.get_week_matchups(league_id, season, week)
        if not matchups or any(matchup.is_playoff for matchup in matchups):
            return None, "incomplete_schedule"
        if active is None and any(not matchup.is_complete for matchup in matchups):
            active = week
    return active, None


def build_projection(
    repository: SyncRepository,
    league_id: int,
    season: int,
    regular_season_length: int,
    cup_week: int | None,
    teams: Sequence[Team],
    completed_weeks: Sequence[int],
    *,
    include_projected: bool,
) -> tuple[int | None, Projection | None]:
    """Return the active week and, when requested, its applied provider projection.

    The result is ``(active_week, None)`` for an ordinary read: the active week is still
    reported so a client can enable its switch. With ``include_projected`` the projection is
    computed from stored ``projected_score`` rows and the real VP engine. Any missing team,
    missing row, or non-regular-season schedule returns an explicit reason and no partial
    week.
    """
    active, schedule_reason = determine_active_week(
        repository, league_id, season, regular_season_length
    )
    if not include_projected:
        return active, None

    league_season = repository.get_league_season(league_id, season)
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
    if completed_weeks and active < completed_weeks[-1]:
        return active, Projection(
            week=None,
            reason="incomplete_schedule",
            as_of=as_of,
            is_cup_week=False,
            teams=(),
        )

    matchups = repository.get_week_matchups(league_id, season, active)
    if not matchups or any(matchup.is_playoff for matchup in matchups):
        return active, Projection(
            week=None,
            reason="incomplete_schedule",
            as_of=as_of,
            is_cup_week=False,
            teams=(),
        )

    roster_ids = {team.id for team in teams}
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

    projection_rows = repository.get_week_projections(league_id, season, active)
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

    is_cup_week = cup_week == active
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

    projected_teams = tuple(
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
        teams=projected_teams,
    )
