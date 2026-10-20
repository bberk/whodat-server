"""Response schemas and serialization for standings and VP history (ARCHITECTURE.md section 8).

VP is computed and accumulated as exact ``Fraction`` values and points as exact ``Decimal``
values. Both cross the wire as strings so no binary float is ever involved. VP is rounded to at
most two decimal places only when it is serialized; the exact values still decide ranks and
cumulative totals. Trailing zeros are trimmed, so ``Fraction(5, 2)`` becomes ``"2.5"`` and
``Decimal("250.00")`` becomes ``"250"``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from pydantic import BaseModel

from app.services.standings_service import StandingRow as ServiceStandingRow
from app.services.standings_service import Standings as ServiceStandings
from app.services.standings_service import VpHistory as ServiceVpHistory

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


class DivisionStandings(BaseModel):
    """A division's rows in overall-rank order; each row keeps its overall league rank."""

    name: str | None
    standings: list[StandingsRow]


class StandingsResponse(BaseModel):
    """Overall standings plus division groupings for one league season."""

    league_id: int
    season: int
    completed_weeks: int
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
    )


def to_standings_response(standings: ServiceStandings) -> StandingsResponse:
    """Build the wire response for standings, reusing one projection for overall and divisions."""
    return StandingsResponse(
        league_id=standings.league_id,
        season=standings.season,
        completed_weeks=standings.completed_weeks,
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
    )
