"""Acceptance tests for the pure standings ranking engine."""

from decimal import Decimal
from fractions import Fraction

import pytest

from app.domain.standings import RankedRow, SeasonRow, rank_teams


def _row(
    team_id: int,
    name: str,
    vp: Fraction | str,
    h2h_wins: int,
    points_for: str,
    division: str | None = None,
) -> SeasonRow:
    """Build a SeasonRow with exact literals (no floats)."""
    return SeasonRow(
        team_id=team_id,
        team_name=name,
        vp=Fraction(vp) if isinstance(vp, str) else vp,
        h2h_wins=h2h_wins,
        points_for=Decimal(points_for),
        division=division,
    )


def _ids(result: list[RankedRow]) -> list[int]:
    return [row.team_id for row in result]


def _ranks(result: list[RankedRow]) -> list[int]:
    return [row.rank for row in result]


def test_empty_input_returns_empty_list() -> None:
    assert rank_teams([]) == []


def test_AC_ST_02_teams_ranked_by_vp_descending() -> None:
    rows = [
        _row(1, "Low", Fraction(5), 3, "900.00"),
        _row(2, "High", Fraction(15), 2, "1000.00"),
        _row(3, "Mid", Fraction(10), 4, "950.00"),
    ]

    result = rank_teams(rows)

    assert _ids(result) == [2, 3, 1]
    assert _ranks(result) == [1, 2, 3]


def test_AC_ST_03_vp_tie_broken_by_h2h_wins_descending() -> None:
    rows = [
        _row(1, "Few Wins", Fraction(10), 2, "1000.00"),
        _row(2, "Many Wins", Fraction(10), 5, "1000.00"),
        _row(3, "Some Wins", Fraction(10), 3, "1000.00"),
    ]

    result = rank_teams(rows)

    assert _ids(result) == [2, 3, 1]
    assert _ranks(result) == [1, 2, 3]


def test_AC_ST_04_points_for_breaks_remaining_ties() -> None:
    rows = [
        _row(1, "Low PF", Fraction(10), 3, "800.00"),
        _row(2, "High PF", Fraction(10), 3, "1200.00"),
        _row(3, "Mid PF", Fraction(10), 3, "1000.00"),
    ]

    result = rank_teams(rows)

    assert _ids(result) == [2, 3, 1]
    assert _ranks(result) == [1, 2, 3]


def test_AC_ST_05_equal_keys_share_rank() -> None:
    rows = [
        _row(1, "Charlie", Fraction(10), 5, "1000.00"),
        _row(2, "Alpha", Fraction(10), 5, "1000.00"),
        _row(3, "Bravo", Fraction(10), 5, "1000.00"),
        _row(4, "Delta", Fraction(5), 2, "800.00"),
    ]

    result = rank_teams(rows)

    # Top three teams share rank 1, Delta is rank 4 (standard competition ranking)
    assert _ranks(result) == [1, 1, 1, 4]
    # Display order alphabetical within the tied group
    assert [r.team_name for r in result[:3]] == ["Alpha", "Bravo", "Charlie"]
    assert result[3].rank == 4
    assert result[3].team_name == "Delta"


def test_AC_ST_05_alphabetical_display_order_only_when_all_keys_equal() -> None:
    """Alphabetical tiebreaker applies only within the fully-tied group."""
    rows = [
        _row(1, "Zulu", Fraction(10), 5, "1000.00"),
        _row(2, "Alpha", Fraction(10), 5, "1000.00"),
        _row(3, "Mike", Fraction(10), 4, "2000.00"),  # fewer wins, more PF
    ]

    result = rank_teams(rows)

    # Zulu and Alpha fully tied, Alpha first alphabetically
    assert result[0].team_name == "Alpha"
    assert result[1].team_name == "Zulu"
    assert result[0].rank == result[1].rank == 1
    # Mike has fewer wins, so ranks lower despite more PF
    assert result[2].team_name == "Mike"
    assert result[2].rank == 3


def test_AC_ST_05_rank_gap_follows_tied_group() -> None:
    """After a tied group, ranks skip to reflect the number of occupied slots."""
    rows = [
        _row(1, "First", Fraction(20), 5, "1000.00"),
        _row(2, "Tied A", Fraction(10), 3, "900.00"),
        _row(3, "Tied B", Fraction(10), 3, "900.00"),
        _row(4, "Tied C", Fraction(10), 3, "900.00"),
        _row(5, "Last", Fraction(5), 1, "500.00"),
    ]

    result = rank_teams(rows)

    assert _ranks(result) == [1, 2, 2, 2, 5]


def test_AC_ST_06_division_tables_display_overall_league_rank() -> None:
    """Division tables show each team's overall league rank, not division-local rank.

    The rank_teams function remains callable on any subset, but production division
    tables reuse the overall ranking and only group rows by division.
    """
    all_rows = [
        _row(1, "East-1", Fraction(15), 5, "1200.00", "East"),
        _row(2, "West-1", Fraction(20), 4, "1100.00", "West"),
        _row(3, "East-2", Fraction(10), 3, "900.00", "East"),
        _row(4, "West-2", Fraction(12), 3, "1000.00", "West"),
        _row(5, "East-3", Fraction(5), 1, "700.00", "East"),
    ]

    # Compute overall ranks first
    overall = rank_teams(all_rows)

    # Division table reuses overall ranks, only filters by division
    east_table = [r for r in overall if r.division == "East"]

    # East teams keep their overall league ranks: East-1 is 2nd overall,
    # East-2 is 4th overall, East-3 is 5th overall
    assert {r.team_id: r.rank for r in east_table} == {1: 2, 3: 4, 5: 5}
    assert [r.team_id for r in east_table] == [1, 3, 5]
    # Division field is preserved on output
    assert all(row.division == "East" for row in east_table)


def test_AC_ST_07_overall_ranking_across_all_rows() -> None:
    """Calling rank_teams on the full list yields overall ranks."""
    rows = [
        _row(1, "East-1", Fraction(15), 5, "1200.00", "East"),
        _row(2, "West-1", Fraction(20), 4, "1100.00", "West"),
        _row(3, "East-2", Fraction(10), 3, "900.00", "East"),
        _row(4, "West-2", Fraction(12), 3, "1000.00", "West"),
        _row(5, "East-3", Fraction(5), 1, "700.00", "East"),
    ]

    overall = rank_teams(rows)

    assert _ids(overall) == [2, 1, 4, 3, 5]
    assert _ranks(overall) == [1, 2, 3, 4, 5]


def test_AC_ST_09_exact_fractional_equality_thirds_sum_to_one() -> None:
    """AC-ST-09: 1/3 + 1/3 + 1/3 equals 1 exactly (no float)."""
    season_vp = Fraction(1, 3) + Fraction(1, 3) + Fraction(1, 3)

    assert season_vp == Fraction(1)
    assert season_vp != Fraction("0.9999999999999999")

    rows = [
        _row(1, "Alpha", season_vp, 3, "1000.00"),
        _row(2, "Beta", Fraction(1), 3, "1000.00"),
        _row(3, "Gamma", Fraction(1), 3, "900.00"),
    ]

    result = rank_teams(rows)

    # Alpha and Beta share rank 1; Gamma is rank 3
    assert result[0].rank == result[1].rank == 1
    assert result[2].rank == 3


def test_results_are_deterministic_and_input_order_independent() -> None:
    """Shuffling input must yield identical output."""
    import random

    rows = [
        _row(1, "A", Fraction(10), 5, "1000.00"),
        _row(2, "B", Fraction(15), 3, "1200.00"),
        _row(3, "C", Fraction(10), 5, "1000.00"),
        _row(4, "D", Fraction(5), 1, "500.00"),
        _row(5, "E", Fraction(15), 3, "1100.00"),
    ]

    baseline = rank_teams(rows)
    shuffled = list(rows)
    rng = random.Random(42)
    for _ in range(20):
        rng.shuffle(shuffled)
        assert rank_teams(shuffled) == baseline


def test_division_none_is_preserved() -> None:
    rows = [_row(1, "No Div", Fraction(10), 3, "1000.00")]

    result = rank_teams(rows)

    assert result[0].division is None


def test_ranked_row_preserves_all_fields() -> None:
    row = _row(7, "Team Seven", Fraction(25, 2), 4, "1234.56", "North")

    result = rank_teams([row])

    assert result[0] == RankedRow(
        rank=1,
        team_id=7,
        team_name="Team Seven",
        vp=Fraction(25, 2),
        h2h_wins=4,
        points_for=Decimal("1234.56"),
        division="North",
    )


def test_vp_ordering_handles_zero_and_negative_values() -> None:
    """Zero and negative VP still sort strictly descending, ties broken by wins then points for."""
    rows = [
        _row(1, "Alpha", Fraction(-5), 0, "500.00"),
        _row(2, "Beta", Fraction(1), 1, "800.00"),
        _row(3, "Gamma", Fraction(-5), 1, "600.00"),
        _row(4, "Delta", Fraction(0), 0, "1000.00"),
    ]

    result = rank_teams(rows)

    assert _ids(result) == [2, 4, 3, 1]
    assert _ranks(result) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "team_count",
    [2, 3, 6, 10, 12],
)
def test_many_teams_rank_without_collisions(team_count: int) -> None:
    """Ladder of strictly-decreasing VP produces ranks 1..N."""
    rows = [
        _row(
            i,
            f"Team-{i:02d}",
            Fraction(team_count * 10 - i),
            team_count - i,
            str(1000 - i),
        )
        for i in range(1, team_count + 1)
    ]

    result = rank_teams(rows)

    assert _ranks(result) == list(range(1, team_count + 1))


def test_all_teams_fully_tied() -> None:
    """When every team is equal on all three keys, all share rank 1."""
    rows = [
        _row(1, "Zulu", Fraction(10), 5, "1000.00"),
        _row(2, "Alpha", Fraction(10), 5, "1000.00"),
        _row(3, "Mike", Fraction(10), 5, "1000.00"),
    ]

    result = rank_teams(rows)

    assert _ranks(result) == [1, 1, 1]
    # Alphabetical display order
    assert [r.team_name for r in result] == ["Alpha", "Mike", "Zulu"]


def test_two_tied_groups() -> None:
    rows = [
        _row(1, "A", Fraction(20), 5, "1500.00"),
        _row(2, "B", Fraction(20), 5, "1500.00"),
        _row(3, "C", Fraction(10), 3, "1000.00"),
        _row(4, "D", Fraction(10), 3, "1000.00"),
        _row(5, "E", Fraction(10), 3, "1000.00"),
    ]

    result = rank_teams(rows)

    assert _ranks(result) == [1, 1, 3, 3, 3]
    # Alphabetical within each tied group
    assert result[0].team_name == "A"
    assert result[1].team_name == "B"
    assert [r.team_name for r in result[2:]] == ["C", "D", "E"]
