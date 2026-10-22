"""Pure tests for WAPDate period availability, ordering, and elimination bounds."""

from decimal import Decimal
from fractions import Fraction

from app.domain.wapdate import (
    PERIODS,
    PeriodWindow,
    TeamPeriodStats,
    build_wapdate_rows,
    offered_periods,
)


def _window(number: int, status: str = "current", weeks: tuple[int, ...] = (1, 2)) -> PeriodWindow:
    """Build a period window for a known period number."""
    period = next(period for period in PERIODS if period.number == number)
    return PeriodWindow(period=period, status=status, weeks=weeks)  # type: ignore[arg-type]


def _team(
    team_id: int,
    name: str,
    vp: int | Fraction,
    wins: int = 0,
    points_for: str = "0.00",
) -> TeamPeriodStats:
    """Build one team's exact period totals."""
    return TeamPeriodStats(
        team_id=team_id,
        team_name=name,
        vp=Fraction(vp),
        wins=wins,
        points_for=Decimal(points_for),
    )


# ---------------------------------------------------------------------------
# Period availability
# ---------------------------------------------------------------------------


def test_AC_WD_02_no_completed_weeks_offers_no_periods() -> None:
    assert offered_periods(()) == ()
    assert offered_periods([0, 13, 14]) == ()


def test_AC_WD_02_partial_period_is_current() -> None:
    windows = offered_periods([1, 2])

    assert len(windows) == 1
    assert windows[0].period.number == 1
    assert windows[0].status == "current"
    assert windows[0].weeks == (1, 2)


def test_AC_WD_02_week_six_offers_complete_period_one_and_current_period_two() -> None:
    windows = offered_periods([1, 2, 3, 4, 5, 6])

    assert [(window.period.number, window.status) for window in windows] == [
        (1, "complete"),
        (2, "current"),
    ]
    assert windows[0].weeks == (1, 2, 3, 4)
    assert windows[1].weeks == (5, 6)


def test_AC_WD_02_period_three_appears_from_week_nine() -> None:
    before = offered_periods([1, 2, 3, 4, 5, 6, 7, 8])
    after = offered_periods([1, 2, 3, 4, 5, 6, 7, 8, 9])

    assert [window.period.number for window in before] == [1, 2]
    assert [(window.period.number, window.status) for window in after] == [
        (1, "complete"),
        (2, "complete"),
        (3, "current"),
    ]


def test_AC_WD_02_all_periods_complete_after_week_twelve() -> None:
    windows = offered_periods(range(1, 13))

    assert [(window.period.number, window.status) for window in windows] == [
        (1, "complete"),
        (2, "complete"),
        (3, "complete"),
    ]
    assert [window.weeks for window in windows] == [
        (1, 2, 3, 4),
        (5, 6, 7, 8),
        (9, 10, 11, 12),
    ]


def test_AC_WD_01_weeks_thirteen_and_later_are_ignored() -> None:
    windows = offered_periods([1, 2, 3, 4, 13, 14, 15])

    assert len(windows) == 1
    assert windows[0].period.number == 1
    assert windows[0].weeks == (1, 2, 3, 4)


def test_AC_WD_02_gaps_still_list_actual_counted_weeks() -> None:
    windows = offered_periods([1, 2, 4, 6])

    assert [(window.period.number, window.status, window.weeks) for window in windows] == [
        (1, "complete", (1, 2, 4)),
        (2, "current", (6,)),
    ]


def test_AC_WD_02_duplicate_and_unsorted_weeks_are_normalized() -> None:
    windows = offered_periods([6, 1, 2, 1, 6])

    assert windows[0].weeks == (1, 2)
    assert windows[1].weeks == (6,)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_AC_WD_04_rows_are_ordered_lowest_first() -> None:
    stats = [
        _team(1, "Alpha", 3, 1, "200.00"),
        _team(2, "Bravo", 3, 0, "250.00"),
        _team(3, "Charlie", 3, 0, "100.00"),
        _team(4, "Delta", -1, 2, "300.00"),
        _team(5, "Echo", 3, 0, "100.00"),
    ]

    rows = build_wapdate_rows(
        stats,
        _window(1, "complete", (1, 2, 3, 4)),
        highest_completed_week=4,
        cup_week=None,
    )

    assert [row.team_name for row in rows] == ["Delta", "Charlie", "Echo", "Bravo", "Alpha"]


def test_AC_WD_01_period_stats_do_not_carry_between_periods() -> None:
    first = build_wapdate_rows(
        [_team(1, "Alpha", 5, 2, "100.00"), _team(2, "Bravo", 1, 0, "80.00")],
        _window(1, "complete", (1, 2, 3, 4)),
        highest_completed_week=4,
        cup_week=None,
    )
    second = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0, "10.00"), _team(2, "Bravo", 3, 1, "20.00")],
        _window(2, "current", (5, 6)),
        highest_completed_week=6,
        cup_week=None,
    )

    assert [(row.team_name, row.vp, row.wins, row.points_for) for row in first] == [
        ("Bravo", Fraction(1), 0, Decimal("80.00")),
        ("Alpha", Fraction(5), 2, Decimal("100.00")),
    ]
    assert [(row.team_name, row.vp, row.wins, row.points_for) for row in second] == [
        ("Alpha", Fraction(0), 0, Decimal("10.00")),
        ("Bravo", Fraction(3), 1, Decimal("20.00")),
    ]


# ---------------------------------------------------------------------------
# Elimination bounds
# ---------------------------------------------------------------------------


def test_AC_WD_06_completed_period_never_greys_a_team() -> None:
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 20, 4, "500.00"), _team(2, "Bravo", 0, 0, "100.00")],
        _window(1, "complete", (1, 2, 3, 4)),
        highest_completed_week=4,
        cup_week=None,
    )

    assert [row.eliminated for row in rows] == [False, False]


def test_AC_WD_05_elimination_uses_strictly_lower_maximum_vp() -> None:
    # Period 1, highest completed week 2: two weeks remain, so a team's minimum is VP - 2
    # and another team's maximum is VP + 6.
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0), _team(2, "Bravo", 9, 2)],
        _window(1, "current", (1, 2)),
        highest_completed_week=2,
        cup_week=None,
    )

    by_name = {row.team_name: row for row in rows}
    assert by_name["Bravo"].eliminated is True
    assert by_name["Alpha"].eliminated is False


def test_AC_WD_05_elimination_uses_equal_vp_and_no_more_maximum_wins() -> None:
    # Alpha's maximum VP is 0 + 6 = 6, equal to Bravo's minimum 8 - 2 = 6, and Alpha's
    # maximum wins (0 + 2) do not exceed Bravo's minimum wins (2).
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0), _team(2, "Bravo", 8, 2)],
        _window(1, "current", (1, 2)),
        highest_completed_week=2,
        cup_week=None,
    )

    by_name = {row.team_name: row for row in rows}
    assert by_name["Bravo"].eliminated is True


def test_AC_WD_05_elimination_does_not_trigger_when_the_trailing_team_can_still_win_more() -> None:
    # Same VP equality, but Alpha can reach 5 wins, more than Bravo's minimum of 2, so Alpha
    # could still finish above Bravo on wins and Bravo is not greyed.
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 0, 3), _team(2, "Bravo", 8, 2)],
        _window(1, "current", (1, 2)),
        highest_completed_week=2,
        cup_week=None,
    )

    by_name = {row.team_name: row for row in rows}
    assert by_name["Bravo"].eliminated is False


def test_AC_WD_05_elimination_bound_gives_a_remaining_cup_week_two_vp_and_no_win() -> None:
    # Period 2, highest week 6: weeks 7 and 8 remain. With week 7 as the cup week, Alpha's
    # maximum VP is 0 + 3 (week 8) + 2 (cup week 7) = 5, equal to Bravo's minimum 7 - 2 = 5,
    # and Alpha's maximum wins are 1, below Bravo's minimum 2.
    with_cup = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0), _team(2, "Bravo", 7, 2)],
        _window(2, "current", (5, 6)),
        highest_completed_week=6,
        cup_week=7,
    )
    # Without the cup week Alpha's maximum VP is 6, above Bravo's minimum, so no greying.
    without_cup = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0), _team(2, "Bravo", 7, 2)],
        _window(2, "current", (5, 6)),
        highest_completed_week=6,
        cup_week=None,
    )

    assert {row.team_name: row.eliminated for row in with_cup}["Bravo"] is True
    assert {row.team_name: row.eliminated for row in without_cup}["Bravo"] is False


def test_AC_WD_05_elimination_ignores_points_for() -> None:
    # Alpha and Bravo tie on minimum/maximum VP and wins; points for would decide the order,
    # but the bound ignores it and still treats Bravo as safe.
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 0, 0, "999.00"), _team(2, "Bravo", 8, 2, "1.00")],
        _window(1, "current", (1, 2)),
        highest_completed_week=2,
        cup_week=None,
    )

    assert {row.team_name: row.eliminated for row in rows}["Bravo"] is True


def test_AC_WD_05_elimination_keeps_a_team_that_can_still_be_last() -> None:
    rows = build_wapdate_rows(
        [_team(1, "Alpha", 4, 1), _team(2, "Bravo", 3, 1), _team(3, "Charlie", 2, 0)],
        _window(1, "current", (1, 2)),
        highest_completed_week=2,
        cup_week=None,
    )

    assert [row.eliminated for row in rows] == [False, False, False]
