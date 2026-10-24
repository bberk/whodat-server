"""Hand-computed acceptance cases for conservative playoff designations."""

from collections.abc import Sequence
from fractions import Fraction

import pytest

from app.domain.clinch import ClinchMatchup, ClinchTeam, compute_clinch_statuses


def _team(
    team_id: int,
    vp: int,
    wins: int = 0,
    division: str | None = None,
) -> ClinchTeam:
    return ClinchTeam(team_id=team_id, vp=Fraction(vp), wins=wins, division=division)


def _calculate(
    teams: Sequence[ClinchTeam],
    matchups: Sequence[ClinchMatchup] = (),
    *,
    completed_weeks: Sequence[int] = (1,),
    regular_season_length: int = 1,
    playoff_team_count: int | None = 2,
    cup_week: int | None = None,
    node_cap: int = 5_000,
) -> dict[int, str | None]:
    return compute_clinch_statuses(
        teams,
        matchups,
        completed_weeks=completed_weeks,
        regular_season_length=regular_season_length,
        playoff_team_count=playoff_team_count,
        cup_week=cup_week,
        node_cap=node_cap,
    )


def _direct_h2h_case(*, cup_week: int | None = None, node_cap: int = 5_000):
    """A/D start on 0, B/C on 6; A plays B and C plays D in the last week."""
    return _calculate(
        [_team(1, 0), _team(2, 6), _team(3, 6), _team(4, 0)],
        [ClinchMatchup(2, 1, 2), ClinchMatchup(2, 3, 4)],
        regular_season_length=2,
        playoff_team_count=2,
        cup_week=cup_week,
        node_cap=node_cap,
    )


def test_AC_PC_01_two_divisions_assign_top_seed_division_berths_and_elimination() -> None:
    """A/D win divisions; B/E take two at-large slots; C/F cannot qualify."""
    teams = [
        _team(1, 20, 8, "East"),
        _team(2, 15, 7, "East"),
        _team(3, 0, 0, "East"),
        _team(4, 10, 5, "West"),
        _team(5, 9, 4, "West"),
        _team(6, 0, 0, "West"),
    ]

    assert _calculate(teams, playoff_team_count=4) == {
        1: "Z",
        2: "X",
        3: "E",
        4: "Y",
        5: "X",
        6: "E",
    }


@pytest.mark.parametrize("division", [None, "Only"])
def test_AC_PC_02_zero_or_one_division_uses_overall_seeding_without_y(
    division: str | None,
) -> None:
    """There is no second auto-berth or Y in a zero/one-division league."""
    teams = [_team(1, 20, division=division), _team(2, 10, division=division)]
    teams.extend([_team(3, 5, division=division), _team(4, 0, division=division)])

    assert _calculate(teams) == {1: "Z", 2: "X", 3: "E", 4: "E"}


def test_AC_PC_03_level_vp_and_wins_at_the_boundary_are_undecided() -> None:
    """PF could break either team's tie, so neither receives a badge or an E."""
    teams = [_team(1, 10, 3), _team(2, 10, 3), _team(3, 0)]

    assert _calculate(teams, playoff_team_count=1) == {1: None, 2: None, 3: "E"}


def test_AC_PC_03_wins_break_a_vp_tie_before_points_for_is_considered() -> None:
    """The VP+wins key is decisive without reading PF when the win totals differ."""
    teams = [_team(1, 10, 4), _team(2, 10, 3)]

    assert _calculate(teams, playoff_team_count=1) == {1: "Z", 2: "E"}


def test_AC_PC_03_tied_division_winner_is_not_a_clinch() -> None:
    """A level VP+wins tie for a division's top spot leaves its winner unresolved."""
    teams = [
        _team(1, 10, 2, "East"),
        _team(2, 10, 2, "East"),
        _team(3, 8, 2, "West"),
        _team(4, 0, 0, "West"),
    ]

    assert _calculate(teams) == {1: None, 2: None, 3: "Y", 4: "E"}


def test_AC_PC_04_exact_late_season_search_respects_direct_h2h_outcomes() -> None:
    """B/C clinch: even a loss leaves them on 5 VP, above A/D's maximum of 3.

    A/D are eliminated because their best decisive win yields 3 VP while the team they beat
    still has 5 and the other 6-VP team has at least 5. The independent root bound is inconclusive
    for B/C, so this also exercises the pruned win/loss/tie search rather than only final tables.
    """
    assert _direct_h2h_case() == {1: "E", 2: "X", 3: "X", 4: "E"}


def test_AC_PC_05_cup_week_counts_rank_vp_but_awards_no_h2h_vp_or_win() -> None:
    """On a cup week C's 4 VP becomes at least 3 and every opponent reaches at most 2.

    On a normal week an opponent can add H2H +1 to that +2 and tie C on VP and wins, making the
    top seed undecided. The cup removes that H2H path, so C is a proven top seed.
    """
    teams = [_team(1, 0), _team(2, 0), _team(3, 4), _team(4, 0)]
    matchups = [ClinchMatchup(2, 1, 2), ClinchMatchup(2, 3, 4)]

    normal = _calculate(teams, matchups, regular_season_length=2)
    cup = _calculate(teams, matchups, regular_season_length=2, cup_week=2)

    assert normal[3] is None
    assert cup == {1: None, 2: None, 3: "Z", 4: None}


def test_AC_PC_06_byes_keep_rank_vp_extremes_without_h2h_games() -> None:
    """Explicit future byes are valid schedule slots and cannot add a win or H2H VP."""
    teams = [_team(1, 100), _team(2, 50), _team(3, 0)]
    byes = [ClinchMatchup(2, team_id, None) for team_id in (1, 2, 3)]

    assert _calculate(teams, byes, regular_season_length=2, playoff_team_count=1) == {
        1: "Z",
        2: "E",
        3: "E",
    }


def test_AC_PC_07_more_than_four_weeks_remaining_disables_all_designations() -> None:
    """The same runaway standings produce badges at four weeks but none at five."""
    teams = [_team(1, 100), _team(2, 0)]
    future = [ClinchMatchup(week, team_id, None) for week in range(2, 7) for team_id in (1, 2)]

    five_remaining = _calculate(
        teams,
        future,
        regular_season_length=6,
        playoff_team_count=1,
    )
    four_remaining = _calculate(
        teams,
        [matchup for matchup in future if matchup.week >= 3],
        completed_weeks=(1, 2),
        regular_season_length=6,
        playoff_team_count=1,
    )

    assert five_remaining == {1: None, 2: None}
    assert four_remaining == {1: "Z", 2: "E"}


def test_AC_PC_08_missing_playoff_metadata_returns_no_designations() -> None:
    """Existing seasons need a re-sync; the calculator never guesses a playoff field size."""
    teams = [_team(1, 100), _team(2, 0)]

    assert _calculate(teams, playoff_team_count=None) == {1: None, 2: None}


def test_AC_PC_09_node_cap_falls_back_to_unknown_instead_of_a_false_badge() -> None:
    """The cap suppresses B/C's searchable X while retaining independently cheap E proofs."""
    assert _direct_h2h_case(node_cap=1) == {1: "E", 2: None, 3: None, 4: "E"}


def test_clinch_single_team_bye_has_zero_net_rank_component_range() -> None:
    """For N=1, high +1 and low -1 cancel, and the top-half pool is empty."""
    result = _calculate(
        [_team(1, 0)],
        [ClinchMatchup(2, 1, None)],
        regular_season_length=2,
        playoff_team_count=1,
    )

    assert result == {1: "Z"}


def test_clinch_empty_and_duplicate_rosters_do_not_invent_badges() -> None:
    """Empty and non-unique team inputs have no meaningful per-team calculation."""
    assert _calculate(()) == {}
    assert _calculate([_team(1, 1), _team(1, 2)]) == {1: None}


@pytest.mark.parametrize(
    "overrides",
    [
        {"regular_season_length": 0},
        {"regular_season_length": True},
        {"node_cap": 0},
        {"node_cap": True},
        {"playoff_team_count": 0},
        {"playoff_team_count": True},
        {"playoff_team_count": 3},
        {"cup_week": 0},
        {"cup_week": 2},
        {"cup_week": True},
        {"completed_weeks": (1, 1)},
        {"completed_weeks": (0,)},
        {"completed_weeks": (2,)},
        {"completed_weeks": (True,)},
    ],
)
def test_clinch_invalid_settings_return_no_designations(
    overrides: dict[str, object],
) -> None:
    """Malformed season settings are unavailable data, not a reason to guess."""
    arguments: dict[str, object] = {
        "teams": [_team(1, 10), _team(2, 0)],
        "playoff_team_count": 1,
    }
    arguments.update(overrides)

    assert _calculate(**arguments) == {1: None, 2: None}  # type: ignore[arg-type]


def test_clinch_negative_wins_return_no_designations() -> None:
    """Invalid current totals cannot support a mathematical proof."""
    assert _calculate([_team(1, 10, -1), _team(2, 0)]) == {1: None, 2: None}


@pytest.mark.parametrize(
    "teams, playoff_team_count",
    [
        (
            [
                _team(1, 10, division="A"),
                _team(2, 8, division="B"),
                _team(3, 0, division="C"),
            ],
            2,
        ),
        ([_team(1, 10, division="A"), _team(2, 0)], 1),
        (
            [_team(1, 10, division="A"), _team(2, 8, division="B"), _team(3, 0)],
            2,
        ),
        ([_team(1, 10, division="A"), _team(2, 0, division="B")], 1),
    ],
)
def test_clinch_unsupported_division_shapes_return_no_designations(
    teams: Sequence[ClinchTeam], playoff_team_count: int
) -> None:
    """More than two divisions or partial division metadata is not a supported seeding shape."""
    assert _calculate(teams, playoff_team_count=playoff_team_count) == {
        team.team_id: None for team in teams
    }


@pytest.mark.parametrize(
    "matchups",
    [
        [ClinchMatchup(1, 1, 2)],
        [ClinchMatchup(2, 99, 2)],
        [ClinchMatchup(2, 1, 99)],
        [ClinchMatchup(2, 1, 1), ClinchMatchup(2, 2, None)],
        [],
        [ClinchMatchup(2, 1, None), ClinchMatchup(2, 1, None)],
    ],
)
def test_clinch_incomplete_or_invalid_future_schedule_returns_no_designations(
    matchups: Sequence[ClinchMatchup],
) -> None:
    """Unknown teams, self games, wrong weeks, and missing/duplicate slots are not schedules."""
    teams = [_team(1, 100), _team(2, 0)]

    assert _calculate(
        teams,
        matchups,
        regular_season_length=2,
        playoff_team_count=1,
    ) == {1: None, 2: None}


def test_clinch_duplicate_participants_with_full_slot_count_are_rejected() -> None:
    """A full-length participant list still must contain every team exactly once."""
    teams = [_team(1, 100), _team(2, 50), _team(3, 0)]
    duplicate = [
        ClinchMatchup(2, 1, None),
        ClinchMatchup(2, 1, None),
        ClinchMatchup(2, 2, None),
    ]

    assert _calculate(
        teams,
        duplicate,
        regular_season_length=2,
        playoff_team_count=1,
    ) == {1: None, 2: None, 3: None}
