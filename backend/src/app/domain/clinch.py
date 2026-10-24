"""Conservative, deterministic playoff clinch and elimination calculations.

The search enumerates every remaining non-cup head-to-head win/loss/tie outcome. Score-ranking VP
components are bounded at their feasible weekly extremes (minimum -1, maximum +2 for a league with
at least two teams). Those bounds relax cross-team score correlation, which can withhold a badge,
but the candidate-worst/candidate-best directions ensure that relaxation can never create one.
Points for is deliberately absent: level VP and wins at a decisive boundary are undecided.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

type ClinchStatus = Literal["X", "Y", "Z", "E"]

_DEFAULT_NODE_CAP = 5_000


@dataclass(frozen=True)
class ClinchTeam:
    """Supply one team's exact completed-week VP, wins, and optional division."""

    team_id: int
    vp: Fraction
    wins: int
    division: str | None


@dataclass(frozen=True)
class ClinchMatchup:
    """Identify one scheduled regular-season slot; an absent away team is a bye."""

    week: int
    home_team_id: int
    away_team_id: int | None


@dataclass(frozen=True)
class _Evaluation:
    definite_playoff: bool
    possible_playoff: bool
    division_winner: bool
    top_seed: bool


@dataclass(frozen=True)
class _Game:
    home: int
    away: int


class _NodeCapExceeded(Exception):
    """Stop one candidate's search without turning an unknown outcome into a badge."""


def compute_clinch_statuses(
    teams: Sequence[ClinchTeam],
    remaining_matchups: Sequence[ClinchMatchup],
    *,
    completed_weeks: Sequence[int],
    regular_season_length: int,
    playoff_team_count: int | None,
    cup_week: int | None,
    node_cap: int = _DEFAULT_NODE_CAP,
) -> dict[int, ClinchStatus | None]:
    """Return each team's proven playoff designation, or None when it is not proven.

    No calculation is attempted with more than four unfinished regular-season weeks. Every
    unfinished week must contain every team exactly once (including explicit byes), and completed
    weeks must be a duplicate-free subset of the season. Two named divisions receive the top two
    seeds; zero or one division uses ordinary overall seeding. Other division shapes, invalid
    settings, and exhausted node budgets conservatively produce no designation.

    Z means a guaranteed top seed, Y a guaranteed division winner without a guaranteed top seed,
    X any other guaranteed berth, and E no possible berth. Search is deterministic and performs
    no I/O. The node cap is per team; other teams keep any independently proven designations.
    """
    result: dict[int, ClinchStatus | None] = {team.team_id: None for team in teams}
    team_ids = frozenset(result)
    if not teams or len(team_ids) != len(teams):
        return result
    if any(team.wins < 0 for team in teams):
        return result
    if not _positive_int(regular_season_length) or not _positive_int(node_cap):
        return result
    if (
        playoff_team_count is None
        or not _positive_int(playoff_team_count)
        or playoff_team_count > len(teams)
    ):
        return result

    if len(set(completed_weeks)) != len(completed_weeks) or any(
        not _positive_int(week) or week > regular_season_length for week in completed_weeks
    ):
        return result
    completed = frozenset(completed_weeks)
    remaining_weeks = tuple(
        week for week in range(1, regular_season_length + 1) if week not in completed
    )
    if len(remaining_weeks) > 4:
        return result
    if cup_week is not None and (not _positive_int(cup_week) or cup_week > regular_season_length):
        return result

    division_names = frozenset(team.division for team in teams if team.division is not None)
    all_divisions = frozenset(team.division for team in teams)
    if len(division_names) > 2 or (len(division_names) == 1 and len(all_divisions) != 1):
        return result
    two_divisions = len(division_names) == 2
    if (two_divisions and (None in all_divisions or playoff_team_count < 2)) or (
        not two_divisions and len(all_divisions) != 1
    ):
        return result
    if not _valid_schedule(remaining_matchups, remaining_weeks, team_ids):
        return result

    ordered_teams = tuple(sorted(teams, key=lambda team: team.team_id))
    games = tuple(
        _Game(matchup.home_team_id, matchup.away_team_id)
        for matchup in sorted(
            remaining_matchups,
            key=lambda matchup: (
                matchup.week,
                matchup.home_team_id,
                matchup.away_team_id or -1,
            ),
        )
        if matchup.week != cup_week and matchup.away_team_id is not None
    )
    for candidate in range(len(ordered_teams)):
        search = _CandidateSearch(
            ordered_teams,
            games,
            candidate=candidate,
            remaining_week_count=len(remaining_weeks),
            playoff_team_count=playoff_team_count,
            two_divisions=two_divisions,
            node_cap=node_cap,
        )
        result[ordered_teams[candidate].team_id] = search.run()
    return result


def _positive_int(value: object) -> bool:
    """Reject booleans and non-positive values where a positive integer is required."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_schedule(
    matchups: Sequence[ClinchMatchup], weeks: Sequence[int], team_ids: frozenset[int]
) -> bool:
    """Require exactly one explicit slot for every team in every unfinished week."""
    expected_weeks = frozenset(weeks)
    participants: dict[int, list[int]] = {week: [] for week in weeks}
    for matchup in matchups:
        if matchup.week not in expected_weeks or matchup.home_team_id not in team_ids:
            return False
        if matchup.away_team_id is not None and (
            matchup.away_team_id not in team_ids or matchup.away_team_id == matchup.home_team_id
        ):
            return False
        participants[matchup.week].append(matchup.home_team_id)
        if matchup.away_team_id is not None:
            participants[matchup.week].append(matchup.away_team_id)
    return all(
        len(participants[week]) == len(team_ids) and frozenset(participants[week]) == team_ids
        for week in weeks
    )


class _CandidateSearch:
    """Prove or refute one candidate's outcomes with bounded depth-first H2H search."""

    def __init__(
        self,
        teams: Sequence[ClinchTeam],
        games: Sequence[_Game],
        *,
        candidate: int,
        remaining_week_count: int,
        playoff_team_count: int,
        two_divisions: bool,
        node_cap: int,
    ) -> None:
        self._teams = teams
        self._games = games
        self._candidate = candidate
        self._remaining_week_count = remaining_week_count
        self._playoff_team_count = playoff_team_count
        self._two_divisions = two_divisions
        self._node_cap = node_cap
        self._index = {team.team_id: index for index, team in enumerate(teams)}
        self._unplayed = [0] * len(teams)
        for game in games:
            self._unplayed[self._index[game.home]] += 1
            self._unplayed[self._index[game.away]] += 1
        self._h2h_vp = [Fraction(0)] * len(teams)
        self._h2h_wins = [0] * len(teams)
        self._nodes = 0
        self._possible_playoff = False
        self._all_playoff = True
        self._all_division = True
        self._all_top = True

    def run(self) -> ClinchStatus | None:
        """Return a proven status, or None if any required scenario remains unresolved."""
        try:
            self._visit(0)
        except _NodeCapExceeded:
            return None
        if not self._possible_playoff:
            return "E"
        if self._all_top:
            return "Z"
        if self._two_divisions and self._all_division:
            return "Y"
        if self._all_playoff:
            return "X"
        return None

    def _visit(self, game_index: int) -> None:
        self._nodes += 1
        if self._nodes > self._node_cap:
            raise _NodeCapExceeded

        worst = self._evaluate(self._keys(candidate_worst=True))
        if worst.definite_playoff:
            self._possible_playoff = True
        best: _Evaluation | None = None
        if not self._possible_playoff:
            best = self._evaluate(self._keys(candidate_worst=False))
            if not best.possible_playoff:
                # No completion of this subtree can produce a berth, so none can produce a
                # division title or a clinch either. Other sibling branches may still be possible.
                self._all_playoff = False
                self._all_division = False
                self._all_top = False

        if game_index == len(self._games):
            self._all_playoff = self._all_playoff and worst.definite_playoff
            self._all_division = self._all_division and worst.division_winner
            self._all_top = self._all_top and worst.top_seed
            if best is not None:
                self._possible_playoff = best.possible_playoff
            return

        needs_playoff = self._all_playoff and not worst.definite_playoff
        needs_division = self._two_divisions and self._all_division and not worst.division_winner
        needs_top = self._all_top and not worst.top_seed
        needs_possible = not self._possible_playoff and best is not None and best.possible_playoff
        if not (needs_playoff or needs_division or needs_top or needs_possible):
            return

        game = self._games[game_index]
        home = self._index[game.home]
        away = self._index[game.away]
        self._unplayed[home] -= 1
        self._unplayed[away] -= 1
        for home_vp, away_vp, home_win, away_win in (
            (Fraction(1), Fraction(0), 1, 0),
            (Fraction(0), Fraction(1), 0, 1),
            (Fraction(1, 2), Fraction(1, 2), 0, 0),
        ):
            self._h2h_vp[home] += home_vp
            self._h2h_vp[away] += away_vp
            self._h2h_wins[home] += home_win
            self._h2h_wins[away] += away_win
            self._visit(game_index + 1)
            self._h2h_vp[home] -= home_vp
            self._h2h_vp[away] -= away_vp
            self._h2h_wins[home] -= home_win
            self._h2h_wins[away] -= away_win
            if self._resolved_unknown():
                break
        self._unplayed[home] += 1
        self._unplayed[away] += 1

    def _resolved_unknown(self) -> bool:
        """Stop once a possible berth and no possible clinch make the result definitely None."""
        division_open = self._two_divisions and self._all_division
        return (
            self._possible_playoff
            and not self._all_top
            and not self._all_playoff
            and not division_open
        )

    def _keys(self, *, candidate_worst: bool) -> list[tuple[Fraction, int]]:
        """Build candidate-worst or candidate-best final VP/wins bounds at this search node."""
        if len(self._teams) == 1:
            rank_minimum = rank_maximum = Fraction(0)
        else:
            rank_minimum, rank_maximum = Fraction(-1), Fraction(2)
        keys: list[tuple[Fraction, int]] = []
        for index, team in enumerate(self._teams):
            is_candidate = index == self._candidate
            favorable = is_candidate != candidate_worst
            rank_value = rank_maximum if favorable else rank_minimum
            unplayed = self._unplayed[index] if favorable else 0
            keys.append(
                (
                    team.vp
                    + self._h2h_vp[index]
                    + rank_value * self._remaining_week_count
                    + unplayed,
                    team.wins + self._h2h_wins[index] + unplayed,
                )
            )
        return keys

    def _evaluate(self, keys: Sequence[tuple[Fraction, int]]) -> _Evaluation:
        if self._two_divisions:
            return self._evaluate_two_divisions(keys)
        candidate_key = keys[self._candidate]
        greater = equal = 0
        for index, key in enumerate(keys):
            if index == self._candidate:
                continue
            if key > candidate_key:
                greater += 1
            elif key == candidate_key:
                equal += 1
        return _Evaluation(
            definite_playoff=greater + equal < self._playoff_team_count,
            possible_playoff=greater < self._playoff_team_count,
            division_winner=False,
            top_seed=greater == 0 and equal == 0,
        )

    def _evaluate_two_divisions(self, keys: Sequence[tuple[Fraction, int]]) -> _Evaluation:
        """Evaluate both auto-berths and at-large berths under every tied winner choice."""
        divisions = sorted({team.division for team in self._teams if team.division is not None})
        first_division, second_division = divisions
        winners: dict[str | None, list[int]] = {}
        for division in (first_division, second_division):
            members = [index for index, team in enumerate(self._teams) if team.division == division]
            top_key = max(keys[index] for index in members)
            winners[division] = [index for index in members if keys[index] == top_key]

        candidate_division = self._teams[self._candidate].division
        other_division = second_division if candidate_division == first_division else first_division
        own_winners = winners[candidate_division]
        division_winner = own_winners == [self._candidate]
        top_seed = division_winner and all(
            keys[self._candidate] > keys[index] for index in winners[other_division]
        )

        definite_playoff = True
        possible_playoff = False
        candidate_key = keys[self._candidate]
        for first_winner in winners[first_division]:
            for second_winner in winners[second_division]:
                winner_ids = {first_winner, second_winner}
                if self._candidate in winner_ids:
                    pair_definite = pair_possible = True
                else:
                    greater = equal = 0
                    for index, key in enumerate(keys):
                        if index in winner_ids or index == self._candidate:
                            continue
                        if key > candidate_key:
                            greater += 1
                        elif key == candidate_key:
                            equal += 1
                    at_large_slots = self._playoff_team_count - 2
                    pair_definite = greater + equal < at_large_slots
                    pair_possible = greater < at_large_slots
                definite_playoff = definite_playoff and pair_definite
                possible_playoff = possible_playoff or pair_possible

        return _Evaluation(
            definite_playoff=definite_playoff,
            possible_playoff=possible_playoff,
            division_winner=division_winner,
            top_seed=top_seed,
        )
