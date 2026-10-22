"""Service-level tests for WAPDate period assembly over synchronized league data."""

import os
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.repositories import SyncRepository
from app.domain.wapdate import WapdateRow
from app.providers.base import MatchupDTO
from app.services.standings_service import StandingsService, WapdatePeriod
from tests.test_standings_service import FOUR_TEAMS, SEASON, _m, _seed


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite database session for each test."""
    engine = create_engine(os.environ.get("REPOSITORY_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _by_name(period: WapdatePeriod) -> dict[str, WapdateRow]:
    """Index a period's rows by team name for readable assertions."""
    return {row.team_name: row for row in period.rows}


def _weeks_1_to_6() -> dict[int, list[MatchupDTO]]:
    """Return a six-week, four-team schedule with distinct weekly scores."""
    return {
        1: [
            _m(1, "team-a", "120.00", "team-d", "90.00"),
            _m(1, "team-b", "110.00", "team-c", "100.00"),
        ],
        2: [
            _m(2, "team-a", "130.00", "team-c", "95.00"),
            _m(2, "team-b", "105.00", "team-d", "115.00"),
        ],
        3: [
            _m(3, "team-a", "100.00", "team-d", "80.00"),
            _m(3, "team-b", "90.00", "team-c", "70.00"),
        ],
        4: [
            _m(4, "team-a", "110.00", "team-c", "85.00"),
            _m(4, "team-b", "95.00", "team-d", "105.00"),
        ],
        5: [
            _m(5, "team-a", "120.00", "team-d", "90.00"),
            _m(5, "team-b", "110.00", "team-c", "100.00"),
        ],
        6: [
            _m(6, "team-a", "130.00", "team-c", "95.00"),
            _m(6, "team-b", "105.00", "team-d", "115.00"),
        ],
    }


def test_AC_WD_02_empty_season_has_no_wapdate_periods(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks={},
        regular_season_length=3,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)

    assert wapdate.highest_completed_week is None
    assert wapdate.periods == ()


def test_AC_WD_02_week_six_offers_period_one_complete_and_period_two_current(
    session: Session,
) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_1_to_6(),
        regular_season_length=8,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)

    assert wapdate.highest_completed_week == 6
    assert [(period.period, period.status, period.weeks) for period in wapdate.periods] == [
        (1, "complete", (1, 2, 3, 4)),
        (2, "current", (5, 6)),
    ]


def test_AC_WD_01_period_stats_do_not_carry_between_periods(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_1_to_6(),
        regular_season_length=8,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)
    first, second = wapdate.periods

    # Period 1's exact totals over weeks 1-4.
    first_rows = _by_name(first)
    assert first_rows["Alpha"].vp == Fraction(12)
    assert first_rows["Alpha"].wins == 4
    assert first_rows["Alpha"].points_for == Decimal("460.00")
    # Period 2 starts from zero: only weeks 5-6 count, not period 1's totals.
    second_rows = _by_name(second)
    assert second_rows["Alpha"].vp == Fraction(6)
    assert second_rows["Alpha"].wins == 2
    assert second_rows["Alpha"].points_for == Decimal("250.00")
    assert second_rows["Alpha"].vp != first_rows["Alpha"].vp


def test_AC_WD_03_cup_week_removes_wins_but_keeps_points_for_and_cup_week_vp(
    session: Session,
) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_1_to_6(),
        regular_season_length=8,
    )
    league_season = SyncRepository(session).get_league_season(seeded.league_id, SEASON)
    assert league_season is not None
    league_season.cup_week = 6
    session.flush()

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)
    current = wapdate.periods[1]

    rows = _by_name(current)
    # Week 5 is a normal week; week 6 is the cup week: no wins, but points and VP still count.
    assert (rows["Alpha"].wins, rows["Bravo"].wins) == (1, 1)
    assert (rows["Charlie"].wins, rows["Delta"].wins) == (0, 0)
    assert rows["Alpha"].points_for == Decimal("250.00")
    assert rows["Delta"].points_for == Decimal("205.00")
    assert rows["Alpha"].vp == Fraction(5)
    assert rows["Bravo"].vp == Fraction(2)
    assert rows["Charlie"].vp == Fraction(-1)
    assert rows["Delta"].vp == Fraction(0)


def test_AC_WD_04_wapdate_rows_are_ordered_lowest_first(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_1_to_6(),
        regular_season_length=8,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)
    first = wapdate.periods[0]

    assert [row.team_name for row in first.rows] == ["Charlie", "Delta", "Bravo", "Alpha"]


def test_AC_WD_06_completed_period_shows_the_actual_result_without_greying(
    session: Session,
) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_1_to_6(),
        regular_season_length=8,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)

    assert wapdate.periods[0].status == "complete"
    assert [row.eliminated for row in wapdate.periods[0].rows] == [False, False, False, False]


def test_AC_WD_05_current_period_greys_a_team_that_cannot_finish_last(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks={
            1: [
                _m(1, "team-a", "120.00", "team-d", "90.00"),
                _m(1, "team-b", "110.00", "team-c", "100.00"),
            ],
            2: [
                _m(2, "team-a", "130.00", "team-d", "80.00"),
                _m(2, "team-b", "100.00", "team-c", "90.00"),
            ],
        },
        regular_season_length=8,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)
    current = wapdate.periods[0]

    assert current.status == "current"
    rows = _by_name(current)
    assert rows["Alpha"].vp == Fraction(6)
    assert rows["Delta"].vp == Fraction(-2)
    assert rows["Alpha"].eliminated is True
    assert rows["Bravo"].eliminated is False
    assert rows["Charlie"].eliminated is False
    assert rows["Delta"].eliminated is False


def test_AC_WD_01_weeks_thirteen_and_later_are_ignored(session: Session) -> None:
    weeks = _weeks_1_to_6()
    weeks[13] = [
        _m(13, "team-a", "150.00", "team-b", "125.00"),
    ]
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=weeks,
        regular_season_length=14,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)

    assert [period.period for period in wapdate.periods] == [1, 2]
    assert wapdate.highest_completed_week == 13


def test_AC_WD_03_exact_fraction_vp_is_kept_for_the_period(session: Session) -> None:
    weeks = {
        week: [
            _m(week, "team-a", "100.00", "team-d", "90.00"),
            _m(week, "team-b", "100.00", "team-c", "80.00"),
        ]
        for week in (1, 2, 3, 4)
    }
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=weeks,
        regular_season_length=4,
    )

    wapdate = StandingsService(session).get_wapdate(seeded.league_id, SEASON)

    rows = _by_name(wapdate.periods[0])
    # Alpha and Bravo tie for the high score every week: 1 H2H + 1 top-half + 1/2 high.
    assert rows["Alpha"].vp == Fraction(10)
    assert rows["Bravo"].vp == Fraction(10)
    assert rows["Alpha"].vp == rows["Bravo"].vp
