"""Acceptance and property tests for the pure weekly VP engine."""

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from app.domain.types import TeamWeek, WeekVP
from app.domain.vp_engine import compute_week_vp


def _week(
    rows: Sequence[tuple[int, str, int | None]],
) -> list[TeamWeek]:
    """Build test weeks while keeping score literals exact and readable."""
    return [
        TeamWeek(team_id=team_id, points=Decimal(points), opponent_id=opponent_id)
        for team_id, points, opponent_id in rows
    ]


def _components(
    result: dict[int, WeekVP],
    team_id: int,
) -> tuple[Fraction, Fraction, Fraction, Fraction, Fraction]:
    """Return a team's components and total for concise acceptance assertions."""
    value = result[team_id]
    return value.h2h, value.top_half, value.high, value.low, value.total


def test_AC_VP_01_h2h_winner_gets_one_and_loser_gets_zero() -> None:
    result = compute_week_vp(_week([(1, "100", 2), (2, "90", 1)]))

    assert result[1].h2h == Fraction(1)
    assert result[2].h2h == Fraction(0)


def test_AC_VP_02_tied_matchup_splits_h2h_equally() -> None:
    result = compute_week_vp(_week([(1, "100", 2), (2, "100", 1)]))

    assert result[1].h2h == result[2].h2h == Fraction(1, 2)


def test_AC_VP_03_top_floor_half_teams_get_one_without_cutoff_tie() -> None:
    week = _week(
        [
            (1, "40", None),
            (2, "30", None),
            (3, "20", None),
            (4, "10", None),
            (5, "0", None),
        ]
    )

    result = compute_week_vp(week)

    assert [result[team_id].top_half for team_id in range(1, 6)] == [
        Fraction(1),
        Fraction(1),
        Fraction(0),
        Fraction(0),
        Fraction(0),
    ]


def test_AC_VP_04_single_high_scorer_gets_one() -> None:
    result = compute_week_vp(_week([(1, "20", None), (2, "10", None)]))

    assert result[1].high == Fraction(1)
    assert result[2].high == Fraction(0)


def test_AC_VP_05_single_low_scorer_gets_minus_one() -> None:
    result = compute_week_vp(_week([(1, "20", None), (2, "10", None)]))

    assert result[1].low == Fraction(0)
    assert result[2].low == Fraction(-1)


def test_AC_VP_06_high_score_tie_splits_one_exactly() -> None:
    result = compute_week_vp(_week([(1, "20", None), (2, "20", None), (3, "10", None)]))

    assert result[1].high == result[2].high == Fraction(1, 2)
    assert result[3].high == Fraction(0)


def test_AC_VP_07_low_score_tie_splits_minus_one_exactly() -> None:
    result = compute_week_vp(_week([(1, "20", None), (2, "10", None), (3, "10", None)]))

    assert result[1].low == Fraction(0)
    assert result[2].low == result[3].low == Fraction(-1, 2)


def test_AC_VP_08_tie_across_top_half_cutoff_shares_in_cutoff_slots() -> None:
    # Example B: C and D occupy ranks three and four, with only one cutoff slot.
    week = _week(
        [
            (1, "130", 5),
            (2, "120", 6),
            (3, "100", 4),
            (4, "100", 3),
            (5, "80", 1),
            (6, "70", 2),
        ]
    )

    result = compute_week_vp(week)

    assert result[3].top_half == result[4].top_half == Fraction(1, 2)
    assert sum((value.top_half for value in result.values()), Fraction(0)) == Fraction(3)


def test_AC_VP_09_bye_has_no_h2h_but_keeps_other_components() -> None:
    result = compute_week_vp(_week([(1, "20", None), (2, "10", None)]))

    assert result[1].h2h == result[2].h2h == Fraction(0)
    assert result[1].top_half == Fraction(1)
    assert result[1].high == Fraction(1)
    assert result[2].low == Fraction(-1)


def test_AC_VP_10_weekly_total_is_sum_of_components() -> None:
    result = compute_week_vp(_week([(1, "10", 2), (2, "10", 1)]))

    assert _components(result, 1) == (
        Fraction(1, 2),
        Fraction(1, 2),
        Fraction(1, 2),
        Fraction(-1, 2),
        Fraction(1),
    )


def test_AC_VP_15_cup_week_scores_no_h2h_but_keeps_other_components() -> None:
    week = _week(
        [
            (1, "130", 3),
            (2, "120", 4),
            (3, "100", 1),
            (4, "90", 2),
        ]
    )

    normal = compute_week_vp(week)
    cup = compute_week_vp(week, h2h=False)

    # The cup week removes only head-to-head VP; every other component is unchanged.
    for team_id in (1, 2, 3, 4):
        assert cup[team_id].h2h == Fraction(0)
        assert cup[team_id].top_half == normal[team_id].top_half
        assert cup[team_id].high == normal[team_id].high
        assert cup[team_id].low == normal[team_id].low
        assert cup[team_id].total == (cup[team_id].top_half + cup[team_id].high + cup[team_id].low)
    assert normal[1].h2h == Fraction(1)
    assert normal[2].h2h == Fraction(1)


def test_AC_VP_11_decimal_scores_compare_exactly_without_float_rounding() -> None:
    equal_values = compute_week_vp(_week([(1, "123.40", None), (2, "123.4", None)]))
    distinct_values = compute_week_vp(_week([(1, "1.0000000000000001", None), (2, "1.0", None)]))

    assert equal_values[1].high == equal_values[2].high == Fraction(1, 2)
    assert distinct_values[1].high == Fraction(1)
    assert distinct_values[2].low == Fraction(-1)


def test_AC_VP_12_results_are_independent_of_input_order() -> None:
    week = _week(
        [
            (1, "120", 6),
            (2, "120", 5),
            (3, "100", 4),
            (4, "90", 3),
            (5, "80", 2),
            (6, "70", 1),
        ]
    )

    assert compute_week_vp(week) == compute_week_vp(list(reversed(week)))


def test_AC_VP_13_empty_week_has_no_awards() -> None:
    assert compute_week_vp([]) == {}


def test_AC_VP_13_example_a_baseline_with_tied_high_score() -> None:
    # Example A from ACCEPTANCE.md.
    result = compute_week_vp(
        _week(
            [
                (1, "120", 6),
                (2, "120", 5),
                (3, "100", 4),
                (4, "90", 3),
                (5, "80", 2),
                (6, "70", 1),
            ]
        )
    )

    assert [_components(result, team_id) for team_id in range(1, 7)] == [
        (Fraction(1), Fraction(1), Fraction(1, 2), Fraction(0), Fraction(5, 2)),
        (Fraction(1), Fraction(1), Fraction(1, 2), Fraction(0), Fraction(5, 2)),
        (Fraction(1), Fraction(1), Fraction(0), Fraction(0), Fraction(2)),
        (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
        (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
        (Fraction(0), Fraction(0), Fraction(0), Fraction(-1), Fraction(-1)),
    ]


def test_AC_VP_13_example_c_tied_low_score() -> None:
    # Example C: the tied low teams are not opponents.
    result = compute_week_vp(_week([(1, "20", None), (2, "10", None), (3, "10", None)]))

    assert result[2].low == result[3].low == Fraction(-1, 2)


def test_AC_VP_13_example_d_three_way_high_tie_uses_thirds() -> None:
    # Example D: exact thirds are retained rather than rounded decimals.
    result = compute_week_vp(
        _week([(1, "20", None), (2, "20", None), (3, "20", None), (4, "10", None)])
    )

    assert [result[team_id].high for team_id in (1, 2, 3)] == [
        Fraction(1, 3),
        Fraction(1, 3),
        Fraction(1, 3),
    ]
    assert sum((result[team_id].high for team_id in (1, 2, 3)), Fraction(0)) == Fraction(1)


@st.composite
def valid_weeks(draw: st.DrawFn) -> list[TeamWeek]:
    """Generate weeks with unique IDs, symmetric matchups, and optional bye."""
    team_count = draw(st.integers(min_value=1, max_value=14))
    points = draw(
        st.lists(
            st.decimals(min_value=Decimal("-1000"), max_value=Decimal("1000"), places=2),
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
        TeamWeek(
            team_id=index + 1,
            points=points[index],
            opponent_id=(None if opponent is None else opponent + 1),
        )
        for index, opponent in enumerate(opponents)
    ]


@given(week=valid_weeks(), data=st.data())
def test_AC_VP_12_property_shuffling_preserves_results(
    week: list[TeamWeek],
    data: st.DataObject,
) -> None:
    shuffled = data.draw(st.permutations(week))

    assert compute_week_vp(week) == compute_week_vp(shuffled)


@given(week=valid_weeks())
def test_AC_VP_13_property_component_sums_match_week_invariants(
    week: list[TeamWeek],
) -> None:
    result = compute_week_vp(week)
    matchup_count = sum(team.opponent_id is not None for team in week) // 2

    assert sum((value.high for value in result.values()), Fraction(0)) == Fraction(1)
    assert sum((value.low for value in result.values()), Fraction(0)) == Fraction(-1)
    assert sum((value.h2h for value in result.values()), Fraction(0)) == Fraction(matchup_count)
