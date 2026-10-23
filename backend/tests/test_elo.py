"""Hand-computed acceptance tests for the pure Elo domain module (AC-Elo-*).

Every expected number here is derived from the documented formula with exact Decimal arithmetic:
an equal-rating win is half of the effective K, a 10-point margin adds 5% to K, and the capped
margin bonus stops growing at the cap. No test touches the database, HTTP layer, clock, or network.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.domain.elo import (
    DEFAULT_K_FACTOR,
    DEFAULT_MARGIN_CAP,
    DEFAULT_STARTING_RATING,
    EloConfig,
    EloMatch,
    EloWeek,
    SeasonInfo,
    compute_elo_history,
    effective_k,
    expected_score,
    margin_multiplier,
    regress_rating,
    update_ratings,
)

D = Decimal
TWO_PLACES = D("0.01")


def plain_config(**overrides: Decimal) -> EloConfig:
    """Return settings with no margin bonus unless a test overrides a field."""
    values: dict[str, Decimal] = {
        "starting_rating": DEFAULT_STARTING_RATING,
        "k_factor": DEFAULT_K_FACTOR,
        "margin_weight": D(0),
        "margin_cap": DEFAULT_MARGIN_CAP,
        "season_regression": D(0),
    }
    values.update(overrides)
    return EloConfig(**values)


def rounded(value: Decimal, places: str = "0.000001") -> Decimal:
    """Round an exact domain value for a readable assertion."""
    return value.quantize(D(places), rounding=ROUND_HALF_UP)


def match(
    home: str,
    away: str | None,
    home_points: str,
    away_points: str | None = None,
    *,
    order: int = 0,
) -> EloMatch:
    """Build one matchup with readable string points."""
    return EloMatch(
        home_key=home,
        away_key=away,
        home_points=D(home_points),
        away_points=D(away_points) if away_points is not None else None,
        order=order,
    )


def week(
    season: int,
    number: int,
    *,
    matches: tuple[EloMatch, ...] = (),
    scores: tuple[tuple[str, str], ...] = (),
    cup: bool = False,
    playoff: bool = False,
    complete: bool = True,
) -> EloWeek:
    """Build one week with readable score strings."""
    return EloWeek(
        season=season,
        week=number,
        is_cup_week=cup,
        is_playoff=playoff,
        is_complete=complete,
        matches=matches,
        scores=tuple((key, D(points)) for key, points in scores),
    )


def season(year: int, *keys: str) -> SeasonInfo:
    """Build one season roster."""
    return SeasonInfo(season=year, team_keys=tuple(keys))


# ---------------------------------------------------------------------------
# Configuration defaults and validation
# ---------------------------------------------------------------------------


def test_AC_Elo_01_default_config_matches_the_documented_values() -> None:
    config = EloConfig()

    assert config.starting_rating == D("1500")
    assert config.k_factor == D("24")
    assert config.margin_weight == D("0.25")
    assert config.margin_cap == D("50")
    assert rounded(config.season_regression) == D("0.333333")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starting_rating", D("999")),
        ("starting_rating", D("2001")),
        ("k_factor", D("0")),
        ("k_factor", D("101")),
        ("margin_weight", D("-0.01")),
        ("margin_weight", D("1.01")),
        ("margin_cap", D("0")),
        ("margin_cap", D("201")),
        ("season_regression", D("-0.01")),
        ("season_regression", D("1.01")),
    ],
)
def test_AC_Elo_02_config_rejects_values_outside_the_documented_ranges(
    field: str, value: Decimal
) -> None:
    with pytest.raises(ValueError):
        EloConfig(**{field: value})


# ---------------------------------------------------------------------------
# Expected score, zero-sum updates, ties, and the margin bonus
# ---------------------------------------------------------------------------


def test_AC_Elo_03_expected_score_is_one_half_between_equal_ratings() -> None:
    assert expected_score(D("1500"), D("1500")) == D("0.5")


def test_AC_Elo_04_expected_scores_are_complementary() -> None:
    for rating_a, rating_b in ((1400, 1600), (1500, 1512), (1800, 1200), (999, 2001)):
        a = expected_score(D(rating_a), D(rating_b))
        b = expected_score(D(rating_b), D(rating_a))
        assert rounded(a + b) == D("1")


def test_AC_Elo_05_plain_update_is_zero_sum() -> None:
    home, away = update_ratings(D("1400"), D("1600"), D(1), D(0), plain_config())

    assert rounded(home + away) == D("3000")
    assert home > D("1400")
    assert away < D("1600")


def test_AC_Elo_06_equal_rating_win_with_plain_k_is_plus_twelve() -> None:
    home, away = update_ratings(D("1500"), D("1500"), D(1), D(0), plain_config())

    assert rounded(home) == D("1512")
    assert rounded(away) == D("1488")


def test_AC_Elo_07_upset_gains_more_than_a_favourite_win() -> None:
    upset, _ = update_ratings(D("1400"), D("1600"), D(1), D(0), plain_config())
    favourite, _ = update_ratings(D("1600"), D("1400"), D(1), D(0), plain_config())

    assert rounded(upset) == D("1418.233926")
    assert rounded(favourite) == D("1605.766074")
    assert upset - D("1400") > favourite - D("1600")


def test_AC_Elo_08_tie_between_equal_ratings_does_not_move() -> None:
    home, away = update_ratings(D("1500"), D("1500"), D("0.5"), D(0), plain_config())

    assert home == D("1500")
    assert away == D("1500")


def test_AC_Elo_09_tie_between_unequal_ratings_moves_toward_the_lower_rated_team() -> None:
    home, away = update_ratings(D("1600"), D("1400"), D("0.5"), D(0), plain_config())

    assert home < D("1600")
    assert away > D("1400")
    assert rounded(home + away) == D("3000")


def test_AC_Elo_10_margin_bonus_uses_the_capped_linear_multiplier() -> None:
    config = plain_config(margin_weight=D("0.25"), margin_cap=D("50"))

    assert margin_multiplier(D(0), config) == D("1")
    assert margin_multiplier(D(10), config) == D("1.05")
    assert margin_multiplier(D(50), config) == D("1.25")
    assert margin_multiplier(D(60), config) == D("1.25")
    assert effective_k(D(10), config) == D("25.2")
    assert effective_k(D(50), config) == D("30")
    assert effective_k(D(60), config) == D("30")


def test_AC_Elo_11_margin_bonus_changes_the_update_at_and_below_the_cap() -> None:
    config = plain_config(margin_weight=D("0.25"), margin_cap=D("50"))

    ten, _ = update_ratings(D("1500"), D("1500"), D(1), D(10), config)
    fifty, _ = update_ratings(D("1500"), D("1500"), D(1), D(50), config)
    sixty, _ = update_ratings(D("1500"), D("1500"), D(1), D(60), config)

    assert rounded(ten) == D("1512.6")
    assert rounded(fifty) == D("1515")
    assert rounded(sixty) == D("1515")


def test_AC_Elo_12_configured_k_factor_scales_the_update() -> None:
    config = plain_config(k_factor=D("48"))

    home, away = update_ratings(D("1500"), D("1500"), D(1), D(0), config)

    assert rounded(home) == D("1524")
    assert rounded(away) == D("1476")


def test_AC_Elo_13_regression_moves_one_third_toward_the_start() -> None:
    config = EloConfig()

    assert rounded(regress_rating(D("1600"), config)) == D("1566.666667")
    assert rounded(regress_rating(D("1400"), config)) == D("1433.333333")
    assert rounded(regress_rating(D("1800"), config)) == D("1700")
    assert rounded(regress_rating(D("1350"), config)) == D("1400")


# ---------------------------------------------------------------------------
# Actual-schedule history
# ---------------------------------------------------------------------------


def test_AC_Elo_14_two_team_week_records_one_post_week_point_per_team() -> None:
    history = compute_elo_history(
        [week(2026, 1, matches=(match("a", "b", "100", "90"),))],
        [season(2026, "a", "b")],
        plain_config(),
        mode="actual_schedule",
    )

    assert [point.week for point in history.weeks] == [1]
    by_key = {team.team_key: team for team in history.teams}
    assert by_key["a"].series == (D("1512"),)
    assert by_key["b"].series == (D("1488"),)
    assert by_key["a"].last_change == D("12")
    assert by_key["b"].last_change == D("-12")


def test_AC_Elo_15_cup_week_is_skipped_in_actual_schedule() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, matches=(match("a", "b", "100", "90"),)),
            week(2026, 2, matches=(match("a", "b", "200", "10"),), cup=True),
            week(2026, 3, matches=(match("a", "b", "100", "90"),)),
        ],
        [season(2026, "a", "b")],
        plain_config(),
        mode="actual_schedule",
    )

    assert [point.rated for point in history.weeks] == [True, False, True]
    assert [point.is_cup_week for point in history.weeks] == [False, True, False]
    by_key = {team.team_key: team for team in history.teams}
    # The cup-week blowout would have moved ratings substantially; the flat point proves it did not.
    assert by_key["a"].series[1] == by_key["a"].series[0]
    assert by_key["b"].series[1] == by_key["b"].series[0]
    assert [rounded(value) for value in by_key["a"].series] == [
        D("1512"),
        D("1512"),
        D("1523.172385"),
    ]


def test_AC_Elo_16_bye_updates_nobody_and_keeps_a_flat_week() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, matches=(match("a", "b", "100", "90"), match("c", None, "80"))),
        ],
        [season(2026, "a", "b", "c")],
        plain_config(),
        mode="actual_schedule",
    )

    by_key = {team.team_key: team for team in history.teams}
    assert history.weeks[0].rated is True
    assert "c" not in by_key
    assert history.unrated_teams == ("c",)


def test_AC_Elo_17_incomplete_and_playoff_weeks_are_excluded() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, matches=(match("a", "b", "100", "90"),), complete=False),
            week(2026, 2, matches=(match("a", "b", "100", "90"),), playoff=True),
        ],
        [season(2026, "a", "b")],
        plain_config(),
        mode="actual_schedule",
    )

    assert history.weeks == ()
    assert history.teams == ()
    assert history.unrated_teams == ("a", "b")


def test_AC_Elo_18_team_appearing_twice_updates_in_deterministic_order() -> None:
    first = match("a", "b", "100", "90", order=1)
    second = match("a", "c", "80", "70", order=2)
    first_history = compute_elo_history(
        [week(2026, 1, matches=(first, second))],
        [season(2026, "a", "b", "c")],
        plain_config(),
        mode="actual_schedule",
    )
    second_history = compute_elo_history(
        [week(2026, 1, matches=(second, first))],
        [season(2026, "a", "b", "c")],
        plain_config(),
        mode="actual_schedule",
    )

    assert first_history.teams == second_history.teams
    a = next(team for team in first_history.teams if team.team_key == "a")
    assert len(a.series) == 1
    assert a.rated_weeks == 1


def test_AC_Elo_19_peak_and_low_include_the_starting_rating() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, matches=(match("a", "b", "120", "90"),)),
            week(2026, 2, matches=(match("b", "a", "130", "80"),)),
        ],
        [season(2026, "a", "b")],
        plain_config(margin_weight=D("0.25"), margin_cap=D("50")),
        mode="actual_schedule",
    )
    a = next(team for team in history.teams if team.team_key == "a")

    assert a.peak == a.series[0]
    assert a.peak_at is not None
    assert (a.peak_at.season, a.peak_at.week) == (2026, 1)
    assert a.low < D("1500")
    assert a.low_at is not None
    assert (a.low_at.season, a.low_at.week) == (2026, 2)


# ---------------------------------------------------------------------------
# Round-robin history
# ---------------------------------------------------------------------------


def test_AC_Elo_20_cup_week_is_rated_in_round_robin() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, scores=(("a", "120"), ("b", "110"))),
            week(2026, 2, scores=(("a", "130"), ("b", "100")), cup=True),
        ],
        [season(2026, "a", "b")],
        plain_config(),
        mode="round_robin",
    )

    assert [point.rated for point in history.weeks] == [True, True]
    by_key = {team.team_key: team for team in history.teams}
    assert [rounded(value) for value in by_key["a"].series] == [D("1512"), D("1523.172385")]
    assert [rounded(value) for value in by_key["b"].series] == [D("1488"), D("1476.827615")]


def test_AC_Elo_21_round_robin_averages_each_teams_pairwise_deltas() -> None:
    history = compute_elo_history(
        [
            week(
                2026,
                1,
                scores=(("a", "120"), ("b", "110"), ("c", "100"), ("d", "90")),
            )
        ],
        [season(2026, "a", "b", "c", "d")],
        plain_config(),
        mode="round_robin",
    )
    by_key = {team.team_key: team for team in history.teams}

    # With K=24 and no margin bonus each pair is worth +12 to the winner; each team's average over
    # three opponents is (3*12)/3 = 12 for A, (1*12 - 2*12)/3 = -4 for C, and so on.
    assert by_key["a"].series == (D("1512"),)
    assert by_key["b"].series == (D("1504"),)
    assert by_key["c"].series == (D("1496"),)
    assert by_key["d"].series == (D("1488"),)
    assert sum(team.series[-1] for team in history.teams) == D("6000")


def test_AC_Elo_22_round_robin_result_does_not_depend_on_score_order() -> None:
    scores = (("a", "120"), ("b", "110"), ("c", "100"), ("d", "90"))
    forward = compute_elo_history(
        [week(2026, 1, scores=scores)],
        [season(2026, "a", "b", "c", "d")],
        plain_config(),
        mode="round_robin",
    )
    reversed_scores = compute_elo_history(
        [week(2026, 1, scores=tuple(reversed(scores)))],
        [season(2026, "a", "b", "c", "d")],
        plain_config(),
        mode="round_robin",
    )

    forward_series = {team.team_key: team.series for team in forward.teams}
    reverse_series = {team.team_key: team.series for team in reversed_scores.teams}

    assert forward_series == reverse_series
    assert [team.team_key for team in forward.teams] == ["a", "b", "c", "d"]


def test_AC_Elo_23_round_robin_requires_every_roster_score() -> None:
    history = compute_elo_history(
        [week(2026, 1, scores=(("a", "120"), ("b", "110")))],
        [season(2026, "a", "b", "c")],
        plain_config(),
        mode="round_robin",
    )

    assert history.weeks[0].rated is False
    assert history.teams == ()
    assert history.unrated_teams == ("a", "b", "c")


# ---------------------------------------------------------------------------
# Seasons, regression, and franchise identity
# ---------------------------------------------------------------------------


def test_AC_Elo_24_regression_runs_before_each_new_season() -> None:
    history = compute_elo_history(
        [
            week(2024, 1, matches=(match("a", "b", "100", "90"),)),
            week(2025, 1, matches=(match("a", "b", "100", "90"),)),
        ],
        [season(2024, "a", "b"), season(2025, "a", "b")],
        EloConfig(margin_weight=D(0)),
        mode="actual_schedule",
    )
    a = next(team for team in history.teams if team.team_key == "a")

    assert a.series[0] == D("1512")
    # 2025 starts at 1508 (1500 + 12*2/3), then another equal-rating win adds 12.
    assert rounded(a.series[1]) == D("1519.447770")
    assert a.seasons[1].start_rating == D("1508")


def test_AC_Elo_25_returning_team_regresses_once_per_missed_season_boundary() -> None:
    history = compute_elo_history(
        [
            week(2024, 1, matches=(match("a", "b", "100", "90"),)),
            week(2026, 1, matches=(match("a", "b", "100", "90"),)),
        ],
        [season(2024, "a", "b"), season(2025, "a", "b"), season(2026, "a", "b")],
        EloConfig(margin_weight=D(0)),
        mode="actual_schedule",
    )
    a = next(team for team in history.teams if team.team_key == "a")

    # Two stored boundaries pass (2024->2025 and 2025->2026): 1500 + 12*(2/3)^2 = 1505.333...
    assert rounded(a.seasons[2].start_rating) == D("1505.333333")


def test_AC_Elo_26_new_franchise_starts_at_the_starting_rating_mid_history() -> None:
    history = compute_elo_history(
        [
            week(2024, 1, matches=(match("a", "b", "100", "90"),)),
            week(2025, 1, matches=(match("a", "c", "100", "120"),)),
        ],
        [season(2024, "a", "b"), season(2025, "a", "b", "c")],
        plain_config(),
        mode="actual_schedule",
    )
    c = next(team for team in history.teams if team.team_key == "c")

    assert c.first_season == 2025
    assert c.series[0] is None
    assert c.series[1] > D("1500")
    assert c.seasons[0].start_rating == D("1500")


def test_AC_Elo_27_team_absent_from_a_season_has_null_series_points() -> None:
    history = compute_elo_history(
        [
            week(2024, 1, matches=(match("a", "b", "100", "90"),)),
            week(2025, 1, matches=(match("a", "c", "100", "90"),)),
            week(2026, 1, matches=(match("a", "b", "100", "90"),)),
        ],
        [
            season(2024, "a", "b"),
            season(2025, "a", "c"),
            season(2026, "a", "b"),
        ],
        plain_config(),
        mode="actual_schedule",
    )
    b = next(team for team in history.teams if team.team_key == "b")

    assert b.series[0] == D("1488")
    assert b.series[1] is None
    assert b.series[2] is not None
    assert b.last_season == 2026


def test_AC_Elo_28_team_order_is_stable_by_first_season_then_key() -> None:
    history = compute_elo_history(
        [
            week(2026, 1, matches=(match("z", "a", "100", "90"),)),
            week(2026, 2, matches=(match("m", "n", "100", "90"),)),
        ],
        [season(2026, "z", "a", "m", "n")],
        plain_config(),
        mode="actual_schedule",
    )

    assert [team.team_key for team in history.teams] == ["a", "m", "n", "z"]


def test_AC_Elo_29_user_facing_strings_round_half_up_to_two_places() -> None:
    from app.api.schemas_elo import format_rating

    assert format_rating(D("12.345")) == "12.35"
    assert format_rating(D("12.344")) == "12.34"
    assert format_rating(D("-0.005")) == "-0.01"
    assert format_rating(D("1500.000")) == "1500"


# ---------------------------------------------------------------------------
# Defensive input handling (still pure and deterministic)
# ---------------------------------------------------------------------------


def test_AC_Elo_35_negative_margin_is_rejected() -> None:
    with pytest.raises(ValueError):
        margin_multiplier(D("-1"), plain_config())


def test_AC_Elo_36_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        compute_elo_history([], [], plain_config(), mode="not-a-mode")  # type: ignore[arg-type]


def test_AC_Elo_37_empty_roster_season_is_ignored() -> None:
    history = compute_elo_history(
        [week(2026, 1, matches=(match("a", "b", "100", "90"),))],
        [season(2026), season(2026, "a", "b")],
        plain_config(),
        mode="actual_schedule",
    )

    assert len(history.teams) == 2


def test_AC_Elo_38_match_with_a_team_outside_the_roster_is_ignored() -> None:
    history = compute_elo_history(
        [week(2026, 1, matches=(match("a", "outsider", "100", "90"),))],
        [season(2026, "a")],
        plain_config(),
        mode="actual_schedule",
    )

    assert [point.rated for point in history.weeks] == [False]
    assert history.unrated_teams == ("a",)


def test_AC_Elo_39_ties_are_half_a_win_in_both_modes() -> None:
    actual = compute_elo_history(
        [week(2026, 1, matches=(match("a", "b", "100", "100"),))],
        [season(2026, "a", "b")],
        plain_config(),
        mode="actual_schedule",
    )
    round_robin = compute_elo_history(
        [week(2026, 1, scores=(("a", "100"), ("b", "100")))],
        [season(2026, "a", "b")],
        plain_config(),
        mode="round_robin",
    )

    for history in (actual, round_robin):
        by_key = {team.team_key: team for team in history.teams}
        assert by_key["a"].series == (D("1500"),)
        assert by_key["b"].series == (D("1500"),)
