"""Response schemas and serialization for standings and VP history (ARCHITECTURE.md section 8).

VP is computed and accumulated as exact ``Fraction`` values and points as exact ``Decimal``
values. Both cross the wire as strings so no binary float is ever involved. VP is rounded to at
most two decimal places only when it is serialized; the exact values still decide ranks and
cumulative totals. Trailing zeros are trimmed, so ``Fraction(5, 2)`` becomes ``"2.5"`` and
``Decimal("250.00")`` becomes ``"250"``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from app.services.standings_service import Projection as ServiceProjection
from app.services.standings_service import StandingRow as ServiceStandingRow
from app.services.standings_service import Standings as ServiceStandings
from app.services.standings_service import VpHistory as ServiceVpHistory
from app.services.standings_service import Wapdate as ServiceWapdate

_TWO_PLACES = Decimal("0.01")


class StandingsRow(BaseModel):
    """One team's overall standing as returned by the standings endpoint."""

    rank: int
    team_id: int
    team_name: str
    owner_name: str | None
    division: str | None
    victory_points: str
    wins: int
    losses: int
    ties: int
    points_for: str
    weekly_vp: list[str]
    clinch: Literal["X", "Y", "Z", "E"] | None
    #: Provider-reported final position including playoffs (1 = champion), or null until reported.
    final_standing: int | None


class DivisionStandings(BaseModel):
    """A division's rows in overall-rank order; each row keeps its overall league rank."""

    name: str | None
    standings: list[StandingsRow]


class ProjectedTeam(BaseModel):
    """One team's provider-projected points and the VP/record they would earn."""

    team_id: int
    opponent_team_id: int | None
    points: str
    victory_points: str


class ProjectionResponse(BaseModel):
    """The active week's provider projection, or why it was not applied.

    ``status`` is ``"ok"`` when the week is included in the response's totals and ``"unavailable"``
    otherwise, with ``reason`` explaining why. ``as_of`` is the last successful fetch, not the
    request time.
    """

    status: Literal["ok", "unavailable"]
    week: int | None
    reason: (
        Literal[
            "no_active_week",
            "projections_not_synced",
            "projections_incomplete",
            "incomplete_schedule",
        ]
        | None
    )
    as_of: datetime | None
    is_cup_week: bool
    teams: list[ProjectedTeam]


class StandingsResponse(BaseModel):
    """Overall standings plus division groupings for one league season."""

    league_id: int
    season: int
    completed_weeks: int
    #: The weeks ``weekly_vp`` aligns to; includes the projected week when it is applied.
    weeks: list[int]
    #: The first incomplete week even when no projected read was requested.
    active_week: int | None
    #: Present only when the request asked for the projected view.
    projection: ProjectionResponse | None
    overall: list[StandingsRow]
    divisions: list[DivisionStandings]


class TeamVpHistory(BaseModel):
    """One team's weekly VP and cumulative VP through each included week."""

    team_id: int
    team_name: str
    weekly: list[str]
    cumulative: list[str]


class VpHistoryResponse(BaseModel):
    """Completed weeks and the per-team series used by the cumulative VP chart."""

    weeks: list[int]
    teams: list[TeamVpHistory]
    #: Weeks in ``weeks`` that came from the active week's provider projection.
    projected_weeks: list[int] = []
    active_week: int | None = None
    projection: ProjectionResponse | None = None


class WapdateRow(BaseModel):
    """One team's WAPDate row, ordered lowest first by the service."""

    team_id: int
    team_name: str
    victory_points: str
    wins: int
    points_for: str
    eliminated: bool


class WapdatePeriod(BaseModel):
    """One offered WAPDate period with its completed weeks and rows."""

    period: int
    start_week: int
    end_week: int
    status: Literal["complete", "current"]
    weeks: list[int]
    rows: list[WapdateRow]


class WapdateResponse(BaseModel):
    """The offered WAPDate periods for one league season."""

    league_id: int
    season: int
    highest_completed_week: int | None
    periods: list[WapdatePeriod]
    projected_week: int | None = None
    projection: ProjectionResponse | None = None


def _trim_display(text: str) -> str:
    """Drop trailing fractional zeros and normalize a negative zero to ``"0"``."""
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def format_vp(value: Fraction) -> str:
    """Serialize an exact VP value with at most two decimals and no trailing zeros.

    The exact fraction is rounded half-up only for display; ranks and cumulative arithmetic use
    the unrounded values. For example ``Fraction(7, 3)`` becomes ``"2.33"`` and
    ``Fraction(-1)`` becomes ``"-1"``.
    """
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return _trim_display(format(exact.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP), "f"))


def format_points(value: Decimal) -> str:
    """Serialize exact points with at most two decimals and no trailing zeros."""
    return _trim_display(format(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP), "f"))


def _row(row: ServiceStandingRow) -> StandingsRow:
    """Project one service row, formatting every exact number as a string."""
    return StandingsRow(
        rank=row.rank,
        team_id=row.team_id,
        team_name=row.team_name,
        owner_name=row.owner_name,
        division=row.division,
        victory_points=format_vp(row.victory_points),
        wins=row.wins,
        losses=row.losses,
        ties=row.ties,
        points_for=format_points(row.points_for),
        weekly_vp=[format_vp(value) for value in row.weekly_vp],
        clinch=row.clinch,
        final_standing=row.final_standing,
    )


def _projection_response(projection: ServiceProjection | None) -> ProjectionResponse | None:
    """Project the service projection (or its absence) onto the wire shape."""
    if projection is None:
        return None
    return ProjectionResponse(
        status="ok" if projection.applied else "unavailable",
        week=projection.week,
        reason=projection.reason,
        as_of=projection.as_of,
        is_cup_week=projection.is_cup_week,
        teams=[
            ProjectedTeam(
                team_id=team.team_id,
                opponent_team_id=team.opponent_team_id,
                points=format_points(team.points),
                victory_points=format_vp(team.victory_points),
            )
            for team in projection.teams
        ],
    )


def to_standings_response(standings: ServiceStandings) -> StandingsResponse:
    """Build the wire response for standings, reusing one projection for overall and divisions."""
    return StandingsResponse(
        league_id=standings.league_id,
        season=standings.season,
        completed_weeks=standings.completed_weeks,
        weeks=list(standings.weeks),
        active_week=standings.active_week,
        projection=_projection_response(standings.projection),
        overall=[_row(row) for row in standings.overall],
        divisions=[
            DivisionStandings(
                name=division.name, standings=[_row(row) for row in division.standings]
            )
            for division in standings.divisions
        ],
    )


def to_vp_history_response(history: ServiceVpHistory) -> VpHistoryResponse:
    """Build the wire response for all completed regular-season weeks."""
    return VpHistoryResponse(
        weeks=list(history.weeks),
        teams=[
            TeamVpHistory(
                team_id=team.team_id,
                team_name=team.team_name,
                weekly=[format_vp(value) for value in team.weekly],
                cumulative=[format_vp(value) for value in team.cumulative],
            )
            for team in history.teams
        ],
        projected_weeks=list(history.projected_weeks),
        active_week=history.active_week,
        projection=_projection_response(history.projection),
    )


def to_wapdate_response(wapdate: ServiceWapdate) -> WapdateResponse:
    """Build the wire response for the offered WAPDate periods."""
    return WapdateResponse(
        league_id=wapdate.league_id,
        season=wapdate.season,
        highest_completed_week=wapdate.highest_completed_week,
        periods=[
            WapdatePeriod(
                period=period.period,
                start_week=period.start_week,
                end_week=period.end_week,
                status=period.status,
                weeks=list(period.weeks),
                rows=[
                    WapdateRow(
                        team_id=row.team_id,
                        team_name=row.team_name,
                        victory_points=format_vp(row.vp),
                        wins=row.wins,
                        points_for=format_points(row.points_for),
                        eliminated=row.eliminated,
                    )
                    for row in period.rows
                ],
            )
            for period in wapdate.periods
        ],
        projected_week=wapdate.projected_week,
        projection=_projection_response(wapdate.projection),
    )
