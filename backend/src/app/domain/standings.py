"""Pure standings ranking with tiebreakers."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction


@dataclass(frozen=True)
class SeasonRow:
    """A team's season statistics for ranking.

    Fields:
        team_id: Unique team identifier
        team_name: Display name for alphabetical tiebreaking
        vp: Exact season VP as sum of weekly Fractions
        h2h_wins: Number of H2H wins (ties don't count per SPEC 3.2)
        points_for: Total points scored in the season
        division: Optional division name for grouping (not for local ranking)
    """

    team_id: int
    team_name: str
    vp: Fraction
    h2h_wins: int
    points_for: Decimal
    division: str | None = None


@dataclass(frozen=True)
class RankedRow:
    """A team with its computed rank in the standings.

    Fields:
        rank: Position in standings (1-indexed, shared for equal keys)
        team_id: Unique team identifier
        team_name: Display name
        vp: Season victory points (exact Fraction)
        h2h_wins: Head-to-head wins count
        points_for: Total points scored
        division: Division name if applicable
    """

    rank: int
    team_id: int
    team_name: str
    vp: Fraction
    h2h_wins: int
    points_for: Decimal
    division: str | None


def rank_teams(rows: Sequence[SeasonRow]) -> list[RankedRow]:
    """Rank teams by VP, H2H wins, and points for with shared ranks for ties.

    Implements the ranking and tiebreak logic:
    - Sort by season VP descending (AC-ST-02)
    - Order VP ties by H2H wins descending (AC-ST-03 ordering clause; whether a tied
      matchup counts as a win is decided upstream)
    - Order remaining ties by points for descending (AC-ST-04)
    - Equal keys share the same rank number (AC-ST-05)
    - Order fully tied teams alphabetically by team name (SPEC 3.2 display rule)
    - Rank any sequence of rows, including the full league (AC-ST-07)
    - Compare with exact Fraction arithmetic, no floats (AC-ST-09)

    Note: AC-ST-01 (season VP aggregation from weekly values), AC-ST-06 (grouping
    overall-ranked rows by division for display), and AC-ST-08 (week filtering for
    playoffs/incomplete weeks) are upstream concerns handled by the caller before
    invoking this function. Production division tables call this once on all rows
    and filter the result by division; they never rank a division subset.

    Returns empty list for empty input. Deterministic and input-order independent.
    """
    if not rows:
        return []

    # Sort by keys descending, then alphabetical by team_name for display order
    sorted_rows = sorted(
        rows,
        key=lambda r: (-r.vp, -r.h2h_wins, -r.points_for, r.team_name),
    )

    ranked: list[RankedRow] = []
    current_rank = 1
    previous_keys: tuple[Fraction, int, Decimal] | None = None

    for position, row in enumerate(sorted_rows, start=1):
        keys = (row.vp, row.h2h_wins, row.points_for)

        # Share rank if keys are identical to previous team
        if previous_keys is not None and keys == previous_keys:
            rank = current_rank
        else:
            rank = position
            current_rank = position

        ranked.append(
            RankedRow(
                rank=rank,
                team_id=row.team_id,
                team_name=row.team_name,
                vp=row.vp,
                h2h_wins=row.h2h_wins,
                points_for=row.points_for,
                division=row.division,
            )
        )
        previous_keys = keys

    return ranked
