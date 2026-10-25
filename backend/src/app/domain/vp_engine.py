"""Pure computation of weekly Victory Points, in exact fractions or integer ticks."""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from app.domain.types import TeamWeek, TeamWeekCents, WeekVP, WeekVPTicks


@dataclass(frozen=True)
class _GroupAward:
    """One tie group's rank-position awards, expressed as slots over the group size."""

    members: tuple[int, ...]
    top_half_slots: int
    high_slots: int
    low_slots: int


def _tie_groups(values: Sequence[Any]) -> list[_GroupAward]:
    """Group indices with equal values in descending order and award their rank slots.

    The top-half pool has ``len(values) // 2`` slots. A group occupying ranks ``r..r+k-1`` (1-based)
    receives ``max(0, min(r+k-1, cutoff) - r + 1)`` slots, split evenly among its ``k`` members. The
    first group owns the high-score point and the last group the low-score point. This is the single
    implementation of the grouping and cutoff arithmetic; the Fraction and integer-tick entry
    points below differ only in how they express the resulting fractions.
    """
    grouped: list[_GroupAward] = []
    order = sorted(range(len(values)), key=values.__getitem__, reverse=True)
    cutoff = len(values) // 2
    position = 0
    rank = 1
    while position < len(order):
        end = position + 1
        value = values[order[position]]
        while end < len(order) and values[order[end]] == value:
            end += 1
        group_size = end - position
        slots = _top_half_slots(rank, group_size, cutoff)
        grouped.append(
            _GroupAward(
                members=tuple(order[position:end]),
                top_half_slots=slots,
                high_slots=1 if position == 0 else 0,
                low_slots=-1 if end == len(order) else 0,
            )
        )
        rank += group_size
        position = end
    return grouped


def compute_week_vp(teams: Sequence[TeamWeek], *, h2h: bool = True) -> dict[int, WeekVP]:
    """Compute exact weekly VP for each team in a valid completed week.

    Opponents are represented symmetrically: both teams in a matchup point to
    one another. Teams with no opponent are byes and receive no H2H VP.

    ``h2h=False`` is for a cup week: every team gets zero head-to-head VP while the top-half,
    high-score, and low-score components are unchanged. The default preserves normal scoring.
    """
    if not teams:
        return {}

    teams_by_id = {team.team_id: team for team in teams}
    groups = _tie_groups([team.points for team in teams])
    h2h_vp = {team.team_id: Fraction(0) for team in teams}
    top_half = {team.team_id: Fraction(0) for team in teams}
    high = {team.team_id: Fraction(0) for team in teams}
    low = {team.team_id: Fraction(0) for team in teams}

    for group in groups:
        group_size = len(group.members)
        for index in group.members:
            team_id = teams[index].team_id
            top_half[team_id] = Fraction(group.top_half_slots, group_size)
            high[team_id] = Fraction(group.high_slots, group_size)
            low[team_id] = Fraction(group.low_slots, group_size)

    if h2h:
        for team in teams:
            opponent_id = team.opponent_id
            if opponent_id is not None and team.team_id < opponent_id:
                opponent = teams_by_id[opponent_id]
                if team.points > opponent.points:
                    h2h_vp[team.team_id] = Fraction(1)
                elif team.points < opponent.points:
                    h2h_vp[opponent_id] = Fraction(1)
                else:
                    h2h_vp[team.team_id] = Fraction(1, 2)
                    h2h_vp[opponent_id] = Fraction(1, 2)

    return {
        team_id: WeekVP(
            team_id=team_id,
            h2h=h2h_vp[team_id],
            top_half=top_half[team_id],
            high=high[team_id],
            low=low[team_id],
        )
        for team_id in sorted(teams_by_id)
    }


def _top_half_slots(rank: int, group_size: int, cutoff: int) -> int:
    """Return how many top-half rank slots a tie group covers."""
    return max(0, min(rank + group_size - 1, cutoff) - rank + 1)


def week_rank_component_ticks(
    scores_cents: Sequence[int], scale: int
) -> tuple[list[int], list[int], list[int]]:
    """Return top-half, high, and low Score VP ticks for each score in input order.

    ``scale`` must be a common multiple of every possible tie-group size (the simulator passes
    ``LCM(1..T, 2)``), so each split is an exact integer number of ticks. This is the hot-path
    equivalent of :func:`_tie_groups`: it walks the same descending tie groups but writes the
    components directly instead of allocating one award object per group.
    """
    count = len(scores_cents)
    top_half = [0] * count
    high = [0] * count
    low = [0] * count
    if count == 0:
        return top_half, high, low

    order = sorted(range(count), key=scores_cents.__getitem__, reverse=True)
    cutoff = count // 2
    rank = 1
    position = 0
    first_size = 0
    last_size = 0
    while position < count:
        end = position + 1
        value = scores_cents[order[position]]
        while end < count and scores_cents[order[end]] == value:
            end += 1
        group_size = end - position
        top_award = _top_half_slots(rank, group_size, cutoff) * scale // group_size
        for cursor in range(position, end):
            top_half[order[cursor]] = top_award
        if position == 0:
            first_size = group_size
        last_size = group_size
        rank += group_size
        position = end

    high_award = scale // first_size
    for index in order[:first_size]:
        high[index] = high_award
    low_award = -scale // last_size
    for index in order[count - last_size :]:
        low[index] = low_award
    return top_half, high, low


def week_h2h_ticks(
    team_ids: Sequence[int],
    scores_cents: Sequence[int],
    opponent_indices: Sequence[int | None],
    scale: int,
) -> list[int]:
    """Return head-to-head VP ticks for each team based on opponent indexes.

    ``opponent_indices`` is aligned with the input order and holds the opponent's index (or
    ``None`` for a bye). Each matchup is counted once, when the lower index is visited; an absent
    opponent earns no head-to-head VP.
    """
    ticks = [0] * len(team_ids)
    for index, opponent_index in enumerate(opponent_indices):
        if opponent_index is None or index >= opponent_index:
            continue
        if scores_cents[index] > scores_cents[opponent_index]:
            ticks[index] += scale
        elif scores_cents[index] < scores_cents[opponent_index]:
            ticks[opponent_index] += scale
        else:
            ticks[index] += scale // 2
            ticks[opponent_index] += scale // 2
    return ticks


def compute_week_vp_tick_components(
    teams: Sequence[TeamWeekCents], *, scale: int, h2h: bool = True
) -> dict[int, WeekVPTicks]:
    """Compute every weekly VP component in exact integer ticks.

    This is the simulator's integer counterpart to :func:`compute_week_vp`: the same groups,
    cutoff slots, splits, byes, and cup-week rule, with ``scale`` as the common denominator. A
    team's total is ``sum(ticks)``, and ``Fraction(total, scale)`` equals the Fraction engine's
    exact total whenever ``scale`` is a multiple of every group size and of two.
    """
    if not teams:
        return {}

    team_ids = [team.team_id for team in teams]
    scores = [team.points_cents for team in teams]
    index_by_id = {team_id: index for index, team_id in enumerate(team_ids)}
    opponent_indices = [
        None if team.opponent_id is None else index_by_id[team.opponent_id] for team in teams
    ]
    top_half, high, low = week_rank_component_ticks(scores, scale)
    h2h_ticks = (
        week_h2h_ticks(team_ids, scores, opponent_indices, scale) if h2h else [0] * len(teams)
    )
    return {
        team.team_id: WeekVPTicks(
            team_id=team.team_id,
            h2h=h2h_ticks[index],
            top_half=top_half[index],
            high=high[index],
            low=low[index],
        )
        for index, team in enumerate(teams)
    }


def compute_week_vp_ticks(
    teams: Sequence[TeamWeekCents], *, scale: int, h2h: bool = True
) -> dict[int, int]:
    """Return each team's exact weekly VP total on the integer tick scale."""
    return {
        team_id: value.total
        for team_id, value in compute_week_vp_tick_components(teams, scale=scale, h2h=h2h).items()
    }
