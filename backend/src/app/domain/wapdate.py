"""Pure WAPDate period standings: fixed four-week periods and last-place elimination bounds.

WAPDate splits the regular season into three fixed, independent periods: weeks 1-4, 5-8 and
9-12. Weeks 13 and later are ignored. A period appears once at least one of its weeks is
completed, and it is complete once the highest completed regular-season week reaches its end
week; otherwise it is the current period.

The module is pure: it imports only the standard library and performs no I/O.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

PeriodStatus = Literal["complete", "current"]


@dataclass(frozen=True)
class Period:
    """One fixed four-week WAPDate period with an inclusive, 1-based week range."""

    number: int
    start_week: int
    end_week: int


PERIODS: tuple[Period, ...] = (
    Period(number=1, start_week=1, end_week=4),
    Period(number=2, start_week=5, end_week=8),
    Period(number=3, start_week=9, end_week=12),
)


@dataclass(frozen=True)
class PeriodWindow:
    """An offered period plus the completed weeks it counts and its display status."""

    period: Period
    status: PeriodStatus
    weeks: tuple[int, ...]


@dataclass(frozen=True)
class TeamPeriodStats:
    """One team's exact totals over a period's completed weeks."""

    team_id: int
    team_name: str
    vp: Fraction
    wins: int
    points_for: Decimal


@dataclass(frozen=True)
class WapdateRow:
    """One team's ordered WAPDate row, with whether it is safe from last place."""

    team_id: int
    team_name: str
    vp: Fraction
    wins: int
    points_for: Decimal
    eliminated: bool


def offered_periods(completed_weeks: Sequence[int]) -> tuple[PeriodWindow, ...]:
    """Return the periods with at least one completed week, in period order.

    ``completed_weeks`` holds the completed regular-season weeks for the season. Weeks 13 and
    later belong to no period and are ignored. A period is ``"complete"`` when the highest
    completed week is at least its end week; otherwise it is ``"current"``. Gaps inside a period
    do not stop it being complete: only the highest completed week decides the status, and
    ``weeks`` lists the weeks that actually counted.
    """
    weeks = tuple(sorted({week for week in completed_weeks if week >= 1}))
    highest = weeks[-1] if weeks else None
    windows: list[PeriodWindow] = []
    for period in PERIODS:
        counted = tuple(week for week in weeks if period.start_week <= week <= period.end_week)
        if not counted:
            continue
        status: PeriodStatus = (
            "complete" if highest is not None and highest >= period.end_week else "current"
        )
        windows.append(PeriodWindow(period=period, status=status, weeks=counted))
    return tuple(windows)


def build_wapdate_rows(
    stats: Sequence[TeamPeriodStats],
    window: PeriodWindow,
    *,
    highest_completed_week: int | None,
    cup_week: int | None,
) -> tuple[WapdateRow, ...]:
    """Order a period's team totals lowest first and mark teams safe from last place.

    The order is VP ascending, then wins ascending, then points for ascending, then team name
    and team id for a stable result. Elimination applies only to a current period. For a team
    with ``r`` remaining weeks, its minimum possible VP is its current VP minus ``r`` (a worst
    score is -1 per week) and its minimum wins are its current wins. Another team's maximum
    possible VP adds +3 per remaining non-cup week and +2 on a remaining cup week (a cup week
    awards no head-to-head VP), and its maximum wins add one per remaining non-cup week. A team
    is greyed when another team's maximum VP is below its minimum VP, or the maxima tie and that
    team's maximum wins do not exceed the team's minimum wins.

    The bounds are deliberately conservative and ignore points for: the extreme weekly VP and
    win outcomes are treated as independently achievable, and an exact VP and wins tie is
    treated as safe even though points for would break it. The flag therefore means "no other
    team can beat this team on the period's VP and wins", not a guarantee about points for.
    """
    ordered = sorted(
        stats,
        key=lambda team: (team.vp, team.wins, team.points_for, team.team_name, team.team_id),
    )
    if window.status != "current" or highest_completed_week is None:
        return tuple(
            WapdateRow(
                team_id=team.team_id,
                team_name=team.team_name,
                vp=team.vp,
                wins=team.wins,
                points_for=team.points_for,
                eliminated=False,
            )
            for team in ordered
        )

    remaining_weeks = tuple(range(highest_completed_week + 1, window.period.end_week + 1))
    remaining_count = len(remaining_weeks)
    cup_remaining = sum(1 for week in remaining_weeks if week == cup_week)
    non_cup_remaining = remaining_count - cup_remaining

    def maximum_vp(team: TeamPeriodStats) -> Fraction:
        return team.vp + 3 * non_cup_remaining + 2 * cup_remaining

    def maximum_wins(team: TeamPeriodStats) -> int:
        return team.wins + non_cup_remaining

    rows: list[WapdateRow] = []
    for team in ordered:
        minimum_vp = team.vp - remaining_count
        minimum_wins = team.wins
        eliminated = any(
            other.team_id != team.team_id
            and (
                maximum_vp(other) < minimum_vp
                or (maximum_vp(other) == minimum_vp and maximum_wins(other) <= minimum_wins)
            )
            for other in ordered
        )
        rows.append(
            WapdateRow(
                team_id=team.team_id,
                team_name=team.team_name,
                vp=team.vp,
                wins=team.wins,
                points_for=team.points_for,
                eliminated=eliminated,
            )
        )
    return tuple(rows)
