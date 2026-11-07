"""WAPDate periodic standings computation service and models."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.db.models import Team
from app.domain.wapdate import (
    PERIODS,
    PeriodWindow,
    TeamPeriodStats,
    WapdateRow,
    build_wapdate_rows,
    offered_periods,
)
from app.services.projection_helpers import Projection


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


class PeriodAggregate(Protocol):
    """Protocol for aggregates providing VP, wins, and points for per team."""

    @property
    def season_vp(self) -> Mapping[int, Fraction]: ...

    @property
    def wins(self) -> Mapping[int, int]: ...

    @property
    def points_for(self) -> Mapping[int, Decimal]: ...


def compute_wapdate(
    league_id: int,
    season: int,
    cup_week: int | None,
    teams: Sequence[Team],
    weeks: Sequence[int],
    highest_completed_week: int | None,
    applied_projection: Projection | None,
    projection: Projection | None,
    aggregate_fn: Callable[[Sequence[int], Projection | None], PeriodAggregate],
) -> Wapdate:
    """Assemble offered WAPDate periods with lowest-first rows for a season."""
    windows = list(offered_periods(weeks))
    if applied_projection is not None and applied_projection.week is not None:
        period = next(
            (
                candidate
                for candidate in PERIODS
                if candidate.start_week <= applied_projection.week <= candidate.end_week
            ),
            None,
        )
        if period is not None and all(window.period.number != period.number for window in windows):
            # The projected week can be the first week of a new period before any of that
            # period's weeks is complete. Offer it as current with no completed weeks; the
            # loop below adds the projected week to its totals.
            windows.append(PeriodWindow(period=period, status="current", weeks=()))
    windows.sort(key=lambda window: window.period.number)

    periods: list[WapdatePeriod] = []
    for window in windows:
        in_period_week: int | None = None
        if (
            applied_projection is not None
            and applied_projection.week is not None
            and window.period.start_week <= applied_projection.week <= window.period.end_week
        ):
            in_period_week = applied_projection.week
        period_projection = applied_projection if in_period_week is not None else None
        aggregate = aggregate_fn(window.weeks, period_projection)
        stats = tuple(
            TeamPeriodStats(
                team_id=team.id,
                team_name=team.name,
                vp=aggregate.season_vp[team.id],
                wins=aggregate.wins[team.id],
                points_for=aggregate.points_for[team.id],
            )
            for team in teams
        )
        effective_highest = in_period_week if in_period_week is not None else highest_completed_week
        rows = build_wapdate_rows(
            stats,
            window,
            highest_completed_week=effective_highest,
            cup_week=cup_week,
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
        highest_completed_week=highest_completed_week,
        periods=tuple(periods),
        projected_week=applied_projection.week if applied_projection is not None else None,
        projection=projection,
    )


class WapdateService:
    """Service to compute WAPDate periods for a league season."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_wapdate(
        self, league_id: int, season: int, *, include_projected: bool = False
    ) -> Wapdate:
        """Return the offered WAPDate periods for a season."""
        from app.services.standings_service import StandingsService

        return StandingsService(self._session).get_wapdate(
            league_id, season, include_projected=include_projected
        )
