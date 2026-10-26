"""Exact acceptance and property tests for the pure playoff-odds simulator."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from math import lcm
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.clinch import ClinchTeam, compute_clinch_statuses
from app.domain.predictions import (
    CountedScore,
    CountedWeek,
    DeterministicDrawSource,
    PredictionUnavailable,
    RemainingMatchup,
    RemainingWeek,
    SeasonPredictionInputs,
    SeasonSimulation,
    SeededDrawSource,
    TeamPredictionCounts,
    TeamSeasonTotals,
    simulate_season,
)
from app.domain.types import TeamWeek, TeamWeekCents, WeekVP
from app.domain.vp_engine import (
    compute_week_vp,
    compute_week_vp_tick_components,
    compute_week_vp_ticks,
    week_rank_component_ticks,
)

PREDICTIONS_PATH = Path(__file__).parents[1] / "src" / "app" / "domain" / "predictions.py"


class FixedDrawSource:
    """Return a fixed sequence of draws, cycling, and fail if a requested bound is too small."""

    def __init__(self, sequence: Sequence[int]) -> None:
        self._sequence = tuple(sequence)
        self._position = 0

    def next_below(self, upper: int) -> int:
        value = self._sequence[self._position % len(self._sequence)]
        self._position += 1
        assert 0 <= value < upper, f"draw {value} is outside 0..{upper - 1}"
        return value


def _team(
    team_id: int,
    name: str,
    division: str | None,
    vp: int | Fraction,
    wins: int,
    points_for: str,
) -> TeamSeasonTotals:
    return TeamSeasonTotals(
        team_id=team_id,
        team_name=name,
        division=division,
        vp=Fraction(vp),
        wins=wins,
        points_for=Decimal(points_for),
    )


def _counted(week: int, scores: Sequence[tuple[int, str]]) -> CountedWeek:
    return CountedWeek(
        week=week,
        scores=tuple(
            CountedScore(team_id=team_id, points=Decimal(points)) for team_id, points in scores
        ),
    )


def _four_team_inputs(
    *,
    teams: tuple[TeamSeasonTotals, ...],
    counted_weeks: tuple[CountedWeek, ...],
    remaining_weeks: tuple[RemainingWeek, ...],
    regular_season_length: int = 2,
    playoff_team_count: int | None = 2,
    cup_week: int | None = None,
) -> SeasonPredictionInputs:
    return SeasonPredictionInputs(
        teams=teams,
        counted_weeks=counted_weeks,
        remaining_weeks=remaining_weeks,
        regular_season_length=regular_season_length,
        playoff_team_count=playoff_team_count,
        cup_week=cup_week,
    )


def _standard_teams() -> tuple[TeamSeasonTotals, ...]:
    return (
        _team(1, "Alpha", "East", 6, 2, "250"),
        _team(2, "Bravo", "East", 2, 1, "215"),
        _team(3, "Charlie", "West", 1, 1, "205"),
        _team(4, "Delta", "West", 0, 0, "195"),
    )


def _standard_counted() -> tuple[CountedWeek, ...]:
    return (
        _counted(1, [(1, "120"), (2, "110"), (3, "100"), (4, "90")]),
        _counted(2, [(1, "130"), (2, "105"), (3, "95"), (4, "115")]),
    )


def _standard_remaining() -> tuple[RemainingWeek, ...]:
    return ()


def _standard_inputs() -> SeasonPredictionInputs:
    return _four_team_inputs(
        teams=_standard_teams(),
        counted_weeks=_standard_counted(),
        remaining_weeks=_standard_remaining(),
    )


def _team_week_cents(
    rows: Sequence[tuple[int, int, int | None]],
) -> list[TeamWeekCents]:
    return [
        TeamWeekCents(team_id=team_id, points_cents=cents, opponent_id=opponent)
        for team_id, cents, opponent in rows
    ]


def _fraction_week(rows: Sequence[tuple[int, int, int | None]]) -> dict[int, WeekVP]:
    return compute_week_vp(
        [
            TeamWeek(
                team_id=team_id,
                points=Decimal(cents) / Decimal(100),
                opponent_id=opponent,
            )
            for team_id, cents, opponent in rows
        ]
    )


@st.composite
def valid_tick_weeks(draw: st.DrawFn) -> list[tuple[int, int, int | None]]:
    """Generate a valid week with unique ids, symmetric matchups, and an optional bye."""
    team_count = draw(st.integers(min_value=1, max_value=14))
    cents = draw(
        st.lists(
            st.integers(min_value=-100_000, max_value=100_000),
            min_size=team_count,
            max_size=team_count,
        )
    )
    pairing_order = draw(st.permutations(tuple(range(team_count))))
    opponents: list[int | None] = [None] * team_count
    for index in range(0, team_count - 1, 2):
        first, second = pairing_order[index : index + 2]
        opponents[first] = second
        opponents[second] = first
    return [
        (index + 1, cents[index], None if opponent is None else opponent + 1)
        for index, opponent in enumerate(opponents)
    ]


# ---------------------------------------------------------------------------
# AC-PO-01/02: the tick engine is exact and the domain has no floats
# ---------------------------------------------------------------------------


def test_AC_PO_01_domain_simulator_uses_no_float() -> None:
    tree = ast.parse(PREDICTIONS_PATH.read_text(encoding="utf-8"))
    float_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    float_names = [
        node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "float"
    ]
    float_literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]

    assert float_calls == []
    assert float_names == []
    assert float_literals == []


@given(week=valid_tick_weeks(), h2h=st.booleans())
def test_AC_PO_02_property_ticks_equal_compute_week_vp(
    week: list[tuple[int, int, int | None]], h2h: bool
) -> None:
    team_count = len(week)
    scale = lcm(*range(1, team_count + 1), 2)
    teams = _team_week_cents(week)
    ticks = compute_week_vp_tick_components(teams, scale=scale, h2h=h2h)
    fractions = compute_week_vp(
        [
            TeamWeek(
                team_id=team_id,
                points=Decimal(cents) / Decimal(100),
                opponent_id=opponent,
            )
            for team_id, cents, opponent in week
        ],
        h2h=h2h,
    )

    assert compute_week_vp_ticks(teams, scale=scale, h2h=h2h) == {
        team_id: value.total for team_id, value in ticks.items()
    }
    for team_id, exact in fractions.items():
        assert Fraction(ticks[team_id].h2h, scale) == exact.h2h
        assert Fraction(ticks[team_id].top_half, scale) == exact.top_half
        assert Fraction(ticks[team_id].high, scale) == exact.high
        assert Fraction(ticks[team_id].low, scale) == exact.low
        assert Fraction(ticks[team_id].total, scale) == exact.total


def test_AC_PO_02_ticks_match_hand_worked_tie_and_bye_weeks() -> None:
    scale = lcm(*range(1, 7), 2)
    week = _team_week_cents(
        [
            (1, 12_000, 6),
            (2, 12_000, 5),
            (3, 10_000, 4),
            (4, 9_000, 3),
            (5, 8_000, 2),
            (6, 7_000, 1),
        ]
    )

    ticks = compute_week_vp_tick_components(week, scale=scale)
    fractions = _fraction_week(
        [
            (1, 12_000, 6),
            (2, 12_000, 5),
            (3, 10_000, 4),
            (4, 9_000, 3),
            (5, 8_000, 2),
            (6, 7_000, 1),
        ]
    )

    for team_id in range(1, 7):
        assert Fraction(ticks[team_id].total, scale) == fractions[team_id].total
    assert Fraction(ticks[1].high, scale) == Fraction(1, 2)
    assert Fraction(ticks[6].low, scale) == Fraction(-1)
    assert compute_week_vp_tick_components([], scale=scale) == {}
    assert compute_week_vp_ticks([], scale=scale) == {}
    assert week_rank_component_ticks([], scale) == ([], [], [])


def test_AC_PO_02_cross_cutoff_and_tied_matchup_split_exactly() -> None:
    row = [(1, 12_000, 4), (2, 11_000, 3), (3, 11_000, 2), (4, 9_000, 1)]
    scale = lcm(*range(1, 5), 2)

    ticks = compute_week_vp_tick_components(_team_week_cents(row), scale=scale)

    # Ranks 2-3 tie across a one-slot cutoff, so each gets half of one top-half slot.
    assert ticks[2].top_half == ticks[3].top_half == scale // 2
    assert ticks[2].h2h == ticks[3].h2h == scale // 2
    assert ticks[1].high == scale
    assert ticks[4].low == -scale
    assert Fraction(ticks[2].total, scale) == _fraction_week(row)[2].total


def test_AC_PO_02_cup_week_has_no_h2h_ticks() -> None:
    row = [(1, 12_000, 2), (2, 11_000, 1), (3, 10_000, None)]
    scale = lcm(*range(1, 4), 2)

    normal = compute_week_vp_tick_components(_team_week_cents(row), scale=scale)
    cup = compute_week_vp_tick_components(_team_week_cents(row), scale=scale, h2h=False)

    assert normal[1].h2h == scale
    assert normal[2].h2h == 0
    assert cup[1].h2h == cup[2].h2h == cup[3].h2h == 0
    assert cup[1].top_half == normal[1].top_half
    assert cup[1].high == normal[1].high
    assert cup[3].low == normal[3].low
    # The bye team earns rank VP but no head-to-head VP.
    assert normal[3].h2h == 0
    assert normal[3].low < 0


# ---------------------------------------------------------------------------
# AC-PO-04/05: seeding, byes, and points for
# ---------------------------------------------------------------------------


def _finished_result(
    teams: tuple[TeamSeasonTotals, ...],
    *,
    playoff_team_count: int,
    regular_season_length: int = 2,
) -> SeasonSimulation:
    counted = tuple(
        CountedWeek(
            week=week,
            scores=tuple(
                CountedScore(team_id=team.team_id, points=team.points_for / 10) for team in teams
            ),
        )
        for week in range(1, regular_season_length + 1)
    )
    outcome = simulate_season(
        SeasonPredictionInputs(
            teams=teams,
            counted_weeks=counted,
            remaining_weeks=(),
            regular_season_length=regular_season_length,
            playoff_team_count=playoff_team_count,
            cup_week=None,
        ),
        iterations=10_000,
    )
    assert isinstance(outcome, SeasonSimulation)
    assert outcome.iterations == 0
    return outcome


def _counts_by_name(result: SeasonSimulation) -> dict[str, TeamPredictionCounts]:
    return {team.team_name: team for team in result.teams}


def test_AC_PO_04_three_divisions_seed_winners_and_cap_byes_at_divisions() -> None:
    teams = (
        _team(1, "East One", "East", 10, 4, "500"),
        _team(2, "East Two", "East", 9, 3, "480"),
        _team(3, "North One", "North", Fraction(17, 2), 3, "470"),
        _team(4, "North Two", "North", 8, 2, "460"),
        _team(5, "West One", "West", 8, 2, "450"),
        _team(6, "West Two", "West", 7, 1, "440"),
        _team(7, "East Three", "East", 1, 0, "400"),
        _team(8, "East Four", "East", 0, 0, "390"),
        _team(9, "North Three", "North", 1, 0, "380"),
        _team(10, "North Four", "North", 0, 0, "370"),
        _team(11, "West Three", "West", 1, 0, "360"),
        _team(12, "West Four", "West", 0, 0, "350"),
    )

    result = _finished_result(teams, playoff_team_count=6)
    counts = _counts_by_name(result)

    # The 6-team bracket is size 8, so two byes go to the top two division winners only.
    assert result.playoff_field == 6
    assert result.division_count == 3
    assert result.bye_count == 2
    assert counts["East One"].bye_count == 1
    assert counts["North One"].bye_count == 1
    assert counts["West One"].bye_count == 0
    assert counts["West One"].division_title_count == 1
    assert counts["West One"].playoff_count == 1
    assert counts["East Two"].playoff_count == 1
    assert counts["North Two"].playoff_count == 1
    assert counts["West Two"].playoff_count == 1
    assert counts["East Three"].playoff_count == 0
    assert sum(team.playoff_count for team in result.teams) == 6
    assert sum(team.bye_count for team in result.teams) == 2


def test_AC_PO_05_worked_example_scenario_one_seeds_division_winners_and_byes() -> None:
    """A three-team bracket has one bye: the better division winner (seed 1)."""
    teams = (
        _team(1, "A", "East", 7, 3, "440"),
        _team(2, "B", "East", Fraction(11, 2), 2, "445"),
        _team(3, "C", "West", Fraction(13, 2), 3, "455"),
        _team(4, "D", "West", -1, 0, "355"),
    )

    counts = _counts_by_name(_finished_result(teams, playoff_team_count=3))

    assert (counts["A"].playoff_count, counts["A"].bye_count, counts["A"].division_title_count) == (
        1,
        1,
        1,
    )
    assert (counts["B"].playoff_count, counts["B"].bye_count, counts["B"].division_title_count) == (
        1,
        0,
        0,
    )
    assert (counts["C"].playoff_count, counts["C"].bye_count, counts["C"].division_title_count) == (
        1,
        0,
        1,
    )
    assert (counts["D"].playoff_count, counts["D"].bye_count, counts["D"].division_title_count) == (
        0,
        0,
        0,
    )


def test_AC_PO_05_worked_example_points_for_decides_the_second_scenario() -> None:
    """Points for breaks level VP and wins; the better division winner takes the only bye."""
    teams = (
        _team(1, "A", "East", 4, 2, "400"),
        _team(2, "B", "East", 4, 2, "410"),
        _team(3, "C", "West", 5, 2, "450"),
        _team(4, "D", "West", 5, 2, "390"),
    )

    counts = _counts_by_name(_finished_result(teams, playoff_team_count=3))

    assert (counts["A"].playoff_count, counts["A"].bye_count, counts["A"].division_title_count) == (
        0,
        0,
        0,
    )
    assert (counts["B"].playoff_count, counts["B"].bye_count, counts["B"].division_title_count) == (
        1,
        0,
        1,
    )
    assert (counts["C"].playoff_count, counts["C"].bye_count, counts["C"].division_title_count) == (
        1,
        1,
        1,
    )
    assert (counts["D"].playoff_count, counts["D"].bye_count, counts["D"].division_title_count) == (
        1,
        0,
        0,
    )


def test_predictions_worked_example_probability_table() -> None:
    scenario_one = _counts_by_name(
        _finished_result(
            (
                _team(1, "A", "East", 7, 3, "440"),
                _team(2, "B", "East", Fraction(11, 2), 2, "445"),
                _team(3, "C", "West", Fraction(13, 2), 3, "455"),
                _team(4, "D", "West", -1, 0, "355"),
            ),
            playoff_team_count=3,
        )
    )
    scenario_two = _counts_by_name(
        _finished_result(
            (
                _team(1, "A", "East", 4, 2, "400"),
                _team(2, "B", "East", 4, 2, "410"),
                _team(3, "C", "West", 5, 2, "450"),
                _team(4, "D", "West", 5, 2, "390"),
            ),
            playoff_team_count=3,
        )
    )

    expected = {
        "A": (Fraction(1, 2), Fraction(1, 2), Fraction(1, 2)),
        "B": (Fraction(1), Fraction(0), Fraction(1, 2)),
        "C": (Fraction(1), Fraction(1, 2), Fraction(1)),
        "D": (Fraction(1, 2), Fraction(0), Fraction(0)),
    }
    for name, (playoff, bye, title) in expected.items():
        assert (
            Fraction(scenario_one[name].playoff_count + scenario_two[name].playoff_count, 2)
            == playoff
        )
        assert Fraction(scenario_one[name].bye_count + scenario_two[name].bye_count, 2) == bye
        assert (
            Fraction(
                scenario_one[name].division_title_count + scenario_two[name].division_title_count,
                2,
            )
            == title
        )


# ---------------------------------------------------------------------------
# AC-PO-06: determinism, analytic paths, and the hot loop
# ---------------------------------------------------------------------------


def _analytic_inputs() -> SeasonPredictionInputs:
    """Three teams, one remaining week, and two equally likely deterministic score paths.

    The counted weeks make every team's own residual pool ``{+d, -d}``; the fixed draw source picks
    the sign for each team in each simulated week.
    """
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
        _team(3, "C", "Only", 0, 0, "0"),
    )
    counted = (
        _counted(1, [(1, "110"), (2, "85"), (3, "85")]),
        _counted(2, [(1, "90"), (2, "115"), (3, "75")]),
    )
    remaining = (RemainingWeek(3, (RemainingMatchup(1, 2), RemainingMatchup(3, None))),)
    return SeasonPredictionInputs(
        teams=teams,
        counted_weeks=counted,
        remaining_weeks=remaining,
        regular_season_length=3,
        playoff_team_count=1,
        cup_week=None,
    )


def test_predictions_analytic_two_paths_are_exactly_half() -> None:
    outcome = simulate_season(
        _analytic_inputs(),
        iterations=2,
        draws=FixedDrawSource([0, 6, 0, 6, 0, 6]),
    )
    assert isinstance(outcome, SeasonSimulation)

    names = [team.team_name for team in outcome.teams]
    assert names == ["A", "B", "C"]
    assert [team.playoff_count for team in outcome.teams] == [1, 1, 0]
    assert [team.division_title_count for team in outcome.teams] == [1, 1, 0]
    assert [team.bye_count for team in outcome.teams] == [0, 0, 0]
    assert outcome.iterations == 2
    assert outcome.remaining_weeks == (3,)
    assert outcome.base_points == (Decimal("96.00"), Decimal("96.00"), Decimal("88.00"))


def test_AC_PO_06_reproducible_for_the_same_seed_and_uses_requested_iterations() -> None:
    inputs = _six_team_inputs()
    first = simulate_season(inputs, iterations=200, draws=SeededDrawSource(1234))
    second = simulate_season(inputs, iterations=200, draws=SeededDrawSource(1234))

    assert isinstance(first, SeasonSimulation)
    assert first == second
    assert first.iterations == 200

    deterministic = simulate_season(inputs, iterations=5)
    repeat = simulate_season(inputs, iterations=5)
    assert isinstance(deterministic, SeasonSimulation)
    assert isinstance(repeat, SeasonSimulation)
    assert deterministic.iterations == 5
    assert deterministic.teams == repeat.teams


def test_predictions_draw_sources_validate_bounds() -> None:
    with pytest.raises(ValueError):
        SeededDrawSource(-1)
    with pytest.raises(ValueError):
        SeededDrawSource(0).next_below(0)
    with pytest.raises(ValueError):
        DeterministicDrawSource().next_below(0)

    source = SeededDrawSource(7)
    assert all(0 <= source.next_below(bound) < bound for bound in (1, 2, 7, 100))
    # A half-range bound makes rejection sampling retry on the first 64-bit draw.
    assert SeededDrawSource(0).next_below(2**63 + 1) < 2**63 + 1
    # A bound wider than one 64-bit word consumes as many words as it needs.
    assert 0 <= SeededDrawSource(3).next_below(2**80) < 2**80


# ---------------------------------------------------------------------------
# AC-PO-03: the score model
# ---------------------------------------------------------------------------


def test_AC_PO_03_shrinks_team_deviation_with_three_pseudo_games() -> None:
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
        _team(3, "C", "Only", 0, 0, "0"),
        _team(4, "D", "Only", 0, 0, "0"),
    )
    counted = (
        _counted(1, [(1, "120"), (2, "100"), (3, "110"), (4, "90")]),
        _counted(2, [(1, "100"), (2, "90"), (3, "130"), (4, "80")]),
    )
    outcome = simulate_season(SeasonPredictionInputs(teams, counted, (), 2, 1, None), iterations=10)

    assert isinstance(outcome, SeasonSimulation)
    assert outcome.base_points == (
        Decimal("105.50"),
        Decimal("99.50"),
        Decimal("109.50"),
        Decimal("95.50"),
    )
    assert outcome.observation_counts == (2, 2, 2, 2)
    assert outcome.uses_two_way_residuals is True
    assert outcome.pooled_residual_count == 8
    assert outcome.confidence == "low"


def test_AC_PO_03_falls_back_to_week_centred_residuals_after_one_week() -> None:
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
        _team(3, "C", "Only", 0, 0, "0"),
    )
    counted = (_counted(1, [(1, "100"), (2, "90")]),)
    outcome = simulate_season(SeasonPredictionInputs(teams, counted, (), 1, 1, None), iterations=10)

    assert isinstance(outcome, SeasonSimulation)
    assert outcome.base_points == (
        Decimal("95.00"),
        Decimal("95.00"),
        Decimal("95.00"),
    )
    assert outcome.observation_counts == (1, 1, 0)
    assert outcome.uses_two_way_residuals is False
    assert outcome.pooled_residual_count == 2


def test_AC_PO_03_teams_with_fewer_than_two_observations_use_the_pooled_pool() -> None:
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
        _team(3, "C", "Only", 0, 0, "0"),
        _team(4, "D", "Only", 0, 0, "0"),
    )
    counted = (
        _counted(1, [(1, "120"), (2, "100"), (3, "110"), (4, "90")]),
        _counted(2, [(1, "100"), (2, "90")]),
    )
    outcome = simulate_season(SeasonPredictionInputs(teams, counted, (), 2, 1, None), iterations=10)

    assert isinstance(outcome, SeasonSimulation)
    assert outcome.observation_counts == (2, 2, 1, 1)
    assert outcome.uses_two_way_residuals is True
    assert outcome.pooled_residual_count == 4


def test_predictions_each_team_in_its_own_division_still_seeds_every_team() -> None:
    teams = tuple(
        _team(index, f"Team {index}", f"Division {index}", 10 - index, 0, str(100 - index))
        for index in range(1, 5)
    )

    outcome = _finished_result(teams, playoff_team_count=4)
    counts = _counts_by_name(outcome)

    assert outcome.division_count == 4
    assert outcome.bye_count == 0
    assert all(team.playoff_count == 1 for team in outcome.teams)
    assert all(counts[f"Team {index}"].division_title_count == 1 for index in range(1, 5))


def test_AC_PO_03_normal_confidence_needs_four_weeks_and_three_observations() -> None:
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
    )
    counted = tuple(
        _counted(week, [(1, str(100 + week)), (2, str(90 + week))]) for week in range(1, 5)
    )
    outcome = simulate_season(SeasonPredictionInputs(teams, counted, (), 4, 2, None), iterations=10)

    assert isinstance(outcome, SeasonSimulation)
    assert outcome.confidence == "normal"
    assert outcome.uses_two_way_residuals is True


# ---------------------------------------------------------------------------
# AC-PO-10: clinch designations are a sanity check on the simulation
# ---------------------------------------------------------------------------


def _clinch_fixture_statuses(playoff_team_count: int) -> dict[int, str | None]:
    teams = [
        ClinchTeam(team_id=1, vp=Fraction(20), wins=8, division="East"),
        ClinchTeam(team_id=2, vp=Fraction(15), wins=7, division="East"),
        ClinchTeam(team_id=3, vp=Fraction(0), wins=0, division="East"),
        ClinchTeam(team_id=4, vp=Fraction(10), wins=5, division="West"),
        ClinchTeam(team_id=5, vp=Fraction(9), wins=4, division="West"),
        ClinchTeam(team_id=6, vp=Fraction(0), wins=0, division="West"),
    ]
    return dict(
        compute_clinch_statuses(
            teams,
            [],
            completed_weeks=(1,),
            regular_season_length=1,
            playoff_team_count=playoff_team_count,
            cup_week=None,
        )
    )


def _clinch_fixture_inputs(playoff_team_count: int) -> SeasonPredictionInputs:
    teams = (
        _team(1, "Alpha", "East", 20, 8, "900"),
        _team(2, "Bravo", "East", 15, 7, "850"),
        _team(3, "Charlie", "East", 0, 0, "500"),
        _team(4, "Delta", "West", 10, 5, "800"),
        _team(5, "Echo", "West", 9, 4, "750"),
        _team(6, "Foxtrot", "West", 0, 0, "450"),
    )
    counted = (_counted(1, [(1, "120"), (2, "110"), (3, "100"), (4, "90"), (5, "80"), (6, "70")]),)
    return SeasonPredictionInputs(teams, counted, (), 1, playoff_team_count, None)


@pytest.mark.parametrize("playoff_team_count", [4, 6])
def test_AC_PO_10_proven_clinch_and_elimination_match_the_simulation(
    playoff_team_count: int,
) -> None:
    statuses = _clinch_fixture_statuses(playoff_team_count)
    outcome = simulate_season(
        _clinch_fixture_inputs(playoff_team_count), iterations=500, draws=SeededDrawSource(99)
    )
    assert isinstance(outcome, SeasonSimulation)
    counts = {team.team_id: team for team in outcome.teams}

    expected_count = 1 if outcome.iterations == 0 else outcome.iterations
    for team_id, status in statuses.items():
        if status in {"X", "Y", "Z"}:
            assert counts[team_id].playoff_count == expected_count
        elif status == "E":
            assert counts[team_id].playoff_count == 0
        if status in {"Y", "Z"} and outcome.bye_count > 0:
            assert counts[team_id].bye_count == expected_count


# ---------------------------------------------------------------------------
# AC-PO-04/06: probability invariants and a pinned golden count set
# ---------------------------------------------------------------------------


def _six_team_inputs() -> SeasonPredictionInputs:
    teams = (
        _team(1, "Alpha", "East", 8, 3, "520"),
        _team(2, "Bravo", "East", 6, 2, "500"),
        _team(3, "Charlie", "East", 2, 1, "460"),
        _team(4, "Delta", "West", 7, 3, "510"),
        _team(5, "Echo", "West", 4, 1, "470"),
        _team(6, "Foxtrot", "West", 1, 0, "430"),
    )
    weekly_scores = (
        [(1, "120.00"), (2, "110.00"), (3, "100.00"), (4, "115.00"), (5, "95.00"), (6, "85.00")],
        [(1, "100.00"), (2, "125.00"), (3, "90.00"), (4, "105.00"), (5, "110.00"), (6, "80.00")],
        [(1, "130.00"), (2, "95.00"), (3, "120.00"), (4, "90.00"), (5, "100.00"), (6, "105.00")],
    )
    counted = tuple(_counted(week, weekly_scores[week - 1]) for week in (1, 2, 3))
    remaining = (
        RemainingWeek(4, (RemainingMatchup(1, 4), RemainingMatchup(2, 5), RemainingMatchup(3, 6))),
        RemainingWeek(5, (RemainingMatchup(1, 5), RemainingMatchup(2, 6), RemainingMatchup(3, 4))),
    )
    return SeasonPredictionInputs(teams, counted, remaining, 5, 4, None)


def test_predictions_probability_invariants_hold_per_run() -> None:
    iterations = 250
    outcome = simulate_season(
        _six_team_inputs(), iterations=iterations, draws=SeededDrawSource(2026)
    )
    assert isinstance(outcome, SeasonSimulation)

    assert sum(team.playoff_count for team in outcome.teams) == iterations * outcome.playoff_field
    assert sum(team.bye_count for team in outcome.teams) == iterations * outcome.bye_count
    assert sum(team.division_title_count for team in outcome.teams) == (
        iterations * outcome.division_count
    )
    assert outcome.bye_count == 0  # a four-team bracket has no first-round byes


def test_predictions_cup_week_adds_no_head_to_head_win() -> None:
    """A cup week's higher score earns rank VP and points for but no win."""
    teams = (
        _team(1, "A", "Only", -1, 2, "100"),
        _team(2, "B", "Only", 2, 1, "110"),
        _team(3, "C", "Only", 0, 0, "50"),
    )
    counted = (_counted(1, [(1, "90"), (2, "80"), (3, "70")]),)
    remaining = (RemainingWeek(2, (RemainingMatchup(1, 2), RemainingMatchup(3, None))),)

    normal = simulate_season(
        SeasonPredictionInputs(teams, counted, remaining, 2, 1, None),
        iterations=1,
        draws=FixedDrawSource([0, 1, 2]),
    )
    cup = simulate_season(
        SeasonPredictionInputs(teams, counted, remaining, 2, 1, 2),
        iterations=1,
        draws=FixedDrawSource([0, 1, 2]),
    )
    assert isinstance(normal, SeasonSimulation)
    assert isinstance(cup, SeasonSimulation)

    normal_counts = {team.team_name: team.playoff_count for team in normal.teams}
    cup_counts = {team.team_name: team.playoff_count for team in cup.teams}
    assert normal_counts == {"A": 1, "B": 0, "C": 0}
    assert cup_counts == {"A": 0, "B": 1, "C": 0}


def test_predictions_golden_seeded_counts() -> None:
    outcome = simulate_season(_six_team_inputs(), iterations=2_000, draws=SeededDrawSource(1234))
    assert isinstance(outcome, SeasonSimulation)

    assert [
        (team.team_name, team.playoff_count, team.bye_count, team.division_title_count)
        for team in outcome.teams
    ] == [
        ("Alpha", 2000, 0, 1659),
        ("Bravo", 1945, 0, 341),
        ("Charlie", 759, 0, 0),
        ("Delta", 1974, 0, 1849),
        ("Echo", 1255, 0, 148),
        ("Foxtrot", 67, 0, 3),
    ]


# ---------------------------------------------------------------------------
# AC-PO-15: the team-strength weight
# ---------------------------------------------------------------------------


_EQUAL_TOTALS_HISTORY = (
    [(1, "120.00"), (2, "110.00"), (3, "100.00"), (4, "115.00"), (5, "95.00"), (6, "85.00")],
    [(1, "100.00"), (2, "125.00"), (3, "90.00"), (4, "105.00"), (5, "110.00"), (6, "80.00")],
    [(1, "130.00"), (2, "95.00"), (3, "120.00"), (4, "90.00"), (5, "100.00"), (6, "105.00")],
)


def _equal_totals_inputs(weight: Decimal, *, alpha_vp: int = 0) -> SeasonPredictionInputs:
    """Six teams with identical current totals and deliberately unequal histories.

    Every team starts from the same VP, wins, and points for, so any difference in the simulated
    probabilities comes from the score model alone. Alpha's history is the strongest and
    Foxtrot's the weakest.
    """
    teams = tuple(
        _team(
            index,
            ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")[index - 1],
            "East" if index <= 3 else "West",
            alpha_vp if index == 1 else 0,
            0,
            "400",
        )
        for index in range(1, 7)
    )
    counted = tuple(_counted(week, _EQUAL_TOTALS_HISTORY[week - 1]) for week in (1, 2, 3))
    remaining = (
        RemainingWeek(4, (RemainingMatchup(1, 4), RemainingMatchup(2, 5), RemainingMatchup(3, 6))),
        RemainingWeek(5, (RemainingMatchup(1, 5), RemainingMatchup(2, 6), RemainingMatchup(3, 4))),
    )
    return SeasonPredictionInputs(teams, counted, remaining, 5, 4, None, weight)


def _playoff_rates(outcome: SeasonSimulation) -> dict[str, Fraction]:
    return {
        team.team_name: Fraction(team.playoff_count, outcome.iterations) for team in outcome.teams
    }


def test_AC_PO_15_weight_zero_gives_every_team_the_same_future_distribution() -> None:
    outcome = simulate_season(
        _equal_totals_inputs(Decimal(0)), iterations=4_000, draws=SeededDrawSource(2026)
    )
    assert isinstance(outcome, SeasonSimulation)

    assert set(outcome.base_points) == {Decimal("104.17")}
    rates = _playoff_rates(outcome)
    # Four of six teams qualify, and with no strength edge every team is interchangeable.
    assert all(abs(Fraction(rate) - Fraction(2, 3)) <= Fraction(3, 100) for rate in rates.values())
    assert max(rates.values()) - min(rates.values()) <= Fraction(3, 100)


def test_AC_PO_15_weight_zero_keeps_current_totals_deciding_seeding() -> None:
    outcome = simulate_season(
        _equal_totals_inputs(Decimal(0), alpha_vp=30),
        iterations=2_000,
        draws=SeededDrawSource(2026),
    )
    assert isinstance(outcome, SeasonSimulation)

    rates = _playoff_rates(outcome)
    assert rates["Alpha"] == 1
    # The other five teams are still interchangeable for the three remaining berths.
    assert all(
        abs(rate - Fraction(3, 5)) <= Fraction(3, 100)
        for name, rate in rates.items()
        if name != "Alpha"
    )


def test_AC_PO_15_weight_zero_makes_a_two_team_matchup_even() -> None:
    """Two unequal histories, one remaining head-to-head, and one playoff berth.

    Exact score ties award half VP and fall to the documented team-name tiebreak, so the rates sit
    within a few points of even rather than exactly at one half.
    """
    teams = (
        _team(1, "Alpha", "Only", 0, 0, "0"),
        _team(2, "Bravo", "Only", 0, 0, "0"),
    )
    counted = tuple(
        _counted(
            week,
            (
                (1, ("130", "120", "140", "110", "125", "135")[week - 1]),
                (2, ("95", "105", "85", "115", "100", "90")[week - 1]),
            ),
        )
        for week in range(1, 7)
    )
    remaining = (RemainingWeek(7, (RemainingMatchup(1, 2),)),)

    even = simulate_season(
        SeasonPredictionInputs(teams, counted, remaining, 7, 1, None, Decimal(0)),
        iterations=4_000,
        draws=SeededDrawSource(11),
    )
    weighted = simulate_season(
        SeasonPredictionInputs(teams, counted, remaining, 7, 1, None),
        iterations=4_000,
        draws=SeededDrawSource(11),
    )
    assert isinstance(even, SeasonSimulation)
    assert isinstance(weighted, SeasonSimulation)

    even_rates = _playoff_rates(even)
    assert all(abs(rate - Fraction(1, 2)) <= Fraction(6, 100) for rate in even_rates.values())
    assert _playoff_rates(weighted)["Alpha"] >= Fraction(4, 5)


def test_AC_PO_15_weight_one_matches_the_default_model_exactly() -> None:
    inputs = _six_team_inputs()
    default = simulate_season(inputs, iterations=500, draws=SeededDrawSource(77))
    explicit = simulate_season(
        replace(inputs, strength_weight=Decimal(1)), iterations=500, draws=SeededDrawSource(77)
    )
    trailing_zeroes = simulate_season(
        replace(inputs, strength_weight=Decimal("1.0")),
        iterations=500,
        draws=SeededDrawSource(77),
    )

    assert isinstance(default, SeasonSimulation)
    assert default == explicit
    assert default == trailing_zeroes


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (Decimal(0), ("102.50", "102.50", "102.50", "102.50")),
        (Decimal("0.5"), ("104.00", "101.00", "106.00", "99.00")),
        (Decimal(1), ("105.50", "99.50", "109.50", "95.50")),
        (Decimal(2), ("108.50", "96.50", "116.50", "88.50")),
        (Decimal(10), ("132.50", "72.50", "172.50", "32.50")),
    ],
)
def test_AC_PO_15_weight_scales_each_base_around_the_grand_mean(
    weight: Decimal, expected: tuple[str, str, str, str]
) -> None:
    teams = (
        _team(1, "A", "Only", 0, 0, "0"),
        _team(2, "B", "Only", 0, 0, "0"),
        _team(3, "C", "Only", 0, 0, "0"),
        _team(4, "D", "Only", 0, 0, "0"),
    )
    counted = (
        _counted(1, [(1, "120"), (2, "100"), (3, "110"), (4, "90")]),
        _counted(2, [(1, "100"), (2, "90"), (3, "130"), (4, "80")]),
    )
    outcome = simulate_season(
        SeasonPredictionInputs(teams, counted, (), 2, 1, None, weight), iterations=10
    )

    assert isinstance(outcome, SeasonSimulation)
    assert outcome.base_points == tuple(Decimal(value) for value in expected)


def test_AC_PO_15_high_weight_increases_the_stronger_teams_projection() -> None:
    default = simulate_season(
        _equal_totals_inputs(Decimal(1)), iterations=2_000, draws=SeededDrawSource(2026)
    )
    amplified = simulate_season(
        _equal_totals_inputs(Decimal(10)), iterations=2_000, draws=SeededDrawSource(2026)
    )
    assert isinstance(default, SeasonSimulation)
    assert isinstance(amplified, SeasonSimulation)

    before = _playoff_rates(default)
    after = _playoff_rates(amplified)
    assert after["Alpha"] > before["Alpha"]
    assert after["Foxtrot"] < before["Foxtrot"]


@pytest.mark.parametrize(
    "weight",
    [
        Decimal(-1),
        Decimal("10.1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0.0000000000000000001"),
    ],
)
def test_AC_PO_15_rejects_an_invalid_weight(weight: Decimal) -> None:
    inputs = replace(_standard_inputs(), strength_weight=weight)
    with pytest.raises(ValueError):
        simulate_season(inputs, iterations=10)


def test_AC_PO_15_accepts_a_high_precision_weight() -> None:
    """An 18-place weight makes the draw bound exceed one 64-bit word; it must still terminate."""
    outcome = simulate_season(
        replace(_six_team_inputs(), strength_weight=Decimal("0.123456789012345678")),
        iterations=50,
        draws=SeededDrawSource(5),
    )

    assert isinstance(outcome, SeasonSimulation)
    assert sum(team.playoff_count for team in outcome.teams) == 50 * outcome.playoff_field


def test_AC_PO_15_canonicalizes_the_weight_and_rejects_excess_precision() -> None:
    from app.domain.predictions import normalize_strength_weight

    assert normalize_strength_weight(Decimal("1.00")) == Decimal(1)
    assert normalize_strength_weight(Decimal("10.000")) == Decimal(10)
    assert normalize_strength_weight(Decimal("-0")) == Decimal(0)
    assert normalize_strength_weight(Decimal("0.500000")) == Decimal("0.5")
    with pytest.raises(ValueError):
        normalize_strength_weight(Decimal("0.1234567890123456789"))
    with pytest.raises(ValueError):
        normalize_strength_weight(Decimal("1e-19"))


# ---------------------------------------------------------------------------
# AC-PO-08: unavailable results instead of guesses
# ---------------------------------------------------------------------------


def _unavailable(inputs: SeasonPredictionInputs) -> str:
    outcome = simulate_season(inputs, iterations=10, draws=SeededDrawSource(1))
    assert isinstance(outcome, PredictionUnavailable)
    return outcome.reason


def test_AC_PO_08_no_completed_weeks_is_unavailable() -> None:
    inputs = replace(
        _standard_inputs(),
        counted_weeks=(),
        remaining_weeks=(
            RemainingWeek(1, (RemainingMatchup(1, 2), RemainingMatchup(3, 4))),
            RemainingWeek(2, (RemainingMatchup(1, 3), RemainingMatchup(2, 4))),
        ),
    )

    assert _unavailable(inputs) == "no_completed_weeks"


@pytest.mark.parametrize(
    "team_changes",
    [
        {"teams": ()},
        {"regular_season_length": 0},
        {
            "teams": (
                _team(1, "Alpha", "East", 1, 0, "100"),
                _team(1, "Bravo", "East", 1, 0, "100"),
            )
        },
    ],
)
def test_AC_PO_08_incomplete_season_shape_is_unavailable(
    team_changes: dict[str, object],
) -> None:
    assert _unavailable(replace(_standard_inputs(), **team_changes)) == "incomplete_schedule"


@pytest.mark.parametrize("division", [None, "", "   "])
def test_AC_PO_08_missing_division_is_unavailable(division: str | None) -> None:
    teams = list(_standard_teams())
    teams[0] = replace(teams[0], division=division)

    assert _unavailable(replace(_standard_inputs(), teams=tuple(teams))) == (
        "unsupported_division_shape"
    )


@pytest.mark.parametrize("playoff_field", [None, 0, True, 1, 5])
def test_AC_PO_08_invalid_playoff_field_is_unavailable(playoff_field: object) -> None:
    inputs = replace(_standard_inputs(), playoff_team_count=playoff_field)  # type: ignore[arg-type]

    assert _unavailable(inputs) == "missing_playoff_field"


@pytest.mark.parametrize(
    "remaining",
    [
        (),
        (
            RemainingWeek(2, (RemainingMatchup(1, 2), RemainingMatchup(3, 4))),
            RemainingWeek(2, (RemainingMatchup(1, 3), RemainingMatchup(2, 4))),
        ),
    ],
)
def test_AC_PO_08_incomplete_week_coverage_is_unavailable(
    remaining: tuple[RemainingWeek, ...],
) -> None:
    inputs = replace(
        _standard_inputs(),
        counted_weeks=(_counted(1, [(1, "100"), (2, "90"), (3, "80"), (4, "70")]),),
        remaining_weeks=remaining,
    )

    assert _unavailable(inputs) == "incomplete_schedule"


@pytest.mark.parametrize(
    "remaining",
    [
        (RemainingWeek(2, (RemainingMatchup(1, 2), RemainingMatchup(3, 4)), is_playoff=True),),
        (RemainingWeek(2, (RemainingMatchup(1, 1), RemainingMatchup(3, 4))),),
        (RemainingWeek(2, (RemainingMatchup(1, 2), RemainingMatchup(1, 3))),),
        (RemainingWeek(2, (RemainingMatchup(1, 99), RemainingMatchup(3, 4))),),
        (RemainingWeek(2, (RemainingMatchup(1, None), RemainingMatchup(2, 99))),),
        (
            RemainingWeek(
                2, (RemainingMatchup(1, 2), RemainingMatchup(3, 4), RemainingMatchup(1, None))
            ),
        ),
    ],
)
def test_AC_PO_08_invalid_remaining_schedule_is_unavailable(
    remaining: tuple[RemainingWeek, ...],
) -> None:
    inputs = replace(
        _standard_inputs(),
        counted_weeks=(_counted(1, [(1, "100"), (2, "90"), (3, "80"), (4, "70")]),),
        remaining_weeks=remaining,
    )

    assert _unavailable(inputs) == "incomplete_schedule"


@pytest.mark.parametrize("cup_week", [0, 3, True])
def test_AC_PO_08_invalid_cup_week_is_unavailable(cup_week: object) -> None:
    inputs = replace(_standard_inputs(), cup_week=cup_week)  # type: ignore[arg-type]

    assert _unavailable(inputs) == "incomplete_schedule"


@pytest.mark.parametrize(
    "counted",
    [
        (CountedWeek(1, ()), _counted(2, [(1, "100"), (2, "90"), (3, "80"), (4, "70")])),
        (
            _counted(1, [(1, "100"), (2, "90"), (3, "80"), (99, "70")]),
            _counted(2, [(1, "100"), (2, "90"), (3, "80"), (4, "70")]),
        ),
    ],
)
def test_AC_PO_08_inconsistent_counted_scores_are_unavailable(
    counted: tuple[CountedWeek, ...],
) -> None:
    assert _unavailable(replace(_standard_inputs(), counted_weeks=counted)) == (
        "incomplete_schedule"
    )


def test_AC_PO_08_finished_season_is_deterministic_and_can_follow_a_cup_week() -> None:
    teams = (
        _team(1, "A", "Only", 5, 2, "200"),
        _team(2, "B", "Only", 4, 1, "190"),
    )
    result = simulate_season(
        SeasonPredictionInputs(
            teams,
            (_counted(1, [(1, "100"), (2, "90")]),),
            (),
            1,
            2,
            1,
        ),
        iterations=0,
    )

    assert isinstance(result, SeasonSimulation)
    assert result.iterations == 0
    assert [team.playoff_count for team in result.teams] == [1, 1]


def test_AC_PO_06_rejects_zero_iterations_while_weeks_remain() -> None:
    with pytest.raises(ValueError):
        simulate_season(_six_team_inputs(), iterations=0)


def _twelve_team_inputs() -> SeasonPredictionInputs:
    """A production-sized fixture: 12 teams, 3 divisions, 6 counted and 6 remaining weeks."""
    teams = tuple(
        _team(
            index,
            f"Team {index:02d}",
            ("East", "North", "West")[(index - 1) // 4],
            Fraction(20 - index, 2),
            (index * 3) % 7,
            str(1000 + index * 13),
        )
        for index in range(1, 13)
    )
    counted = tuple(
        _counted(
            week,
            [(index, f"{80 + index * 3 + week * 2}.00") for index in range(1, 13)],
        )
        for week in range(1, 7)
    )
    remaining = tuple(
        RemainingWeek(
            week,
            tuple(
                RemainingMatchup(
                    home_team_id=(offset + slot) % 12 + 1,
                    away_team_id=(11 - slot + offset) % 12 + 1,
                )
                for slot in range(6)
            ),
        )
        for offset, week in enumerate(range(7, 13))
    )
    return SeasonPredictionInputs(teams, counted, remaining, 12, 6, None)


@pytest.mark.slow
def test_predictions_ten_thousand_iterations_fit_the_performance_budget() -> None:
    from time import perf_counter

    inputs = _twelve_team_inputs()
    started = perf_counter()
    outcome = simulate_season(inputs, iterations=10_000, draws=SeededDrawSource(7))
    elapsed = perf_counter() - started

    assert isinstance(outcome, SeasonSimulation)
    assert sum(team.playoff_count for team in outcome.teams) == 10_000 * 6
    # Deliberately generous: the documented local benchmark is well under one second, and this
    # guard only catches an order-of-magnitude regression on slower CI hardware.
    assert elapsed < 5.0
