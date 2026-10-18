"""Pure computation of weekly Victory Points."""

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

from app.domain.types import TeamWeek, WeekVP


def compute_week_vp(teams: Sequence[TeamWeek]) -> dict[int, WeekVP]:
    """Compute exact weekly VP for each team in a valid completed week.

    Opponents are represented symmetrically: both teams in a matchup point to
    one another. Teams with no opponent are byes and receive no H2H VP.
    """
    if not teams:
        return {}

    teams_by_id = {team.team_id: team for team in teams}
    scores: dict[Decimal, list[TeamWeek]] = {}
    for team in teams:
        scores.setdefault(team.points, []).append(team)

    groups = [
        sorted(group, key=lambda team: team.team_id)
        for _, group in sorted(scores.items(), key=lambda item: item[0], reverse=True)
    ]
    h2h = {team.team_id: Fraction(0) for team in teams}
    top_half = {team.team_id: Fraction(0) for team in teams}
    high = {team.team_id: Fraction(0) for team in teams}
    low = {team.team_id: Fraction(0) for team in teams}

    cutoff = len(teams) // 2
    rank = 1
    for group in groups:
        group_size = len(group)
        slots = max(0, min(rank + group_size - 1, cutoff) - rank + 1)
        award = Fraction(slots, group_size)
        for team in group:
            top_half[team.team_id] = award
        rank += group_size

    high_award = Fraction(1, len(groups[0]))
    for team in groups[0]:
        high[team.team_id] = high_award

    low_award = Fraction(-1, len(groups[-1]))
    for team in groups[-1]:
        low[team.team_id] = low_award

    for team in teams:
        opponent_id = team.opponent_id
        if opponent_id is not None and team.team_id < opponent_id:
            opponent = teams_by_id[opponent_id]
            if team.points > opponent.points:
                h2h[team.team_id] = Fraction(1)
            elif team.points < opponent.points:
                h2h[opponent_id] = Fraction(1)
            else:
                h2h[team.team_id] = Fraction(1, 2)
                h2h[opponent_id] = Fraction(1, 2)

    return {
        team_id: WeekVP(
            team_id=team_id,
            h2h=h2h[team_id],
            top_half=top_half[team_id],
            high=high[team_id],
            low=low[team_id],
        )
        for team_id in sorted(teams_by_id)
    }
