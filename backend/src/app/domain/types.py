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
