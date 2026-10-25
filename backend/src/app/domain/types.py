"""Immutable values shared by the pure domain calculations."""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction


@dataclass(frozen=True)
class TeamWeek:
    """A team's exact score and opponent for one completed week."""

    team_id: int
    points: Decimal
    opponent_id: int | None


@dataclass(frozen=True)
class WeekVP:
    """Victory Point components awarded to one team for one week."""

    team_id: int
    h2h: Fraction
    top_half: Fraction
    high: Fraction
    low: Fraction

    @property
    def total(self) -> Fraction:
        """Return the exact sum of the team's weekly VP components."""
        return self.h2h + self.top_half + self.high + self.low


@dataclass(frozen=True)
class TeamWeekCents:
    """A team's integer-cent score and optional opponent for one simulated week.

    Scores are whole cents and byes use ``opponent_id=None``; this keeps the simulation's hot
    loop free of ``Decimal`` and ``Fraction`` while preserving the engine's exact rules.
    """

    team_id: int
    points_cents: int
    opponent_id: int | None


@dataclass(frozen=True)
class WeekVPTicks:
    """Victory Point components on the simulator's exact integer tick scale."""

    team_id: int
    h2h: int
    top_half: int
    high: int
    low: int

    @property
    def total(self) -> int:
        """Return the exact integer sum of the team's weekly VP ticks."""
        return self.h2h + self.top_half + self.high + self.low
