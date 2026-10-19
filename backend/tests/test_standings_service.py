"""Service-level acceptance tests for standings aggregation and VP history.

Every test builds stored data through the FakeProvider and SyncService (plus a league_season
settings row, which is a separate persistence concern), then reads it back through
StandingsService. No live provider calls are made.
"""

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.repositories import SyncRepository
from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)
from app.providers.fake import FakeProvider
from app.services.standings_service import (
    DivisionStandings,
    LeagueNotFoundError,
    SeasonNotFoundError,
    SeasonSettingsError,
    StandingRow,
    Standings,
    StandingsService,
    TeamDataError,
)
from app.services.sync_service import SyncService

LEAGUE_EXTERNAL_ID = "league-1"
SEASON = 2026


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


@dataclass(frozen=True)
class SeededLeague:
    """Identify the league and season teams written by a test seed."""

    league_id: int
    team_ids: Mapping[str, int]


def _m(
    week: int,
    home: str,
    home_points: str,
    away: str | None,
    away_points: str | None,
    *,
    is_playoff: bool = False,
    is_complete: bool = True,
) -> MatchupDTO:
    """Build a normalized matchup DTO; away=None denotes a bye."""
    away_side = (
        MatchupSideDTO(team_external_id=away, points=Decimal(away_points))
        if away is not None and away_points is not None
        else None
    )
    return MatchupDTO(
        week=week,
        home=MatchupSideDTO(team_external_id=home, points=Decimal(home_points)),
        away=away_side,
        is_playoff=is_playoff,
        is_complete=is_complete,
    )


def _seed(
    session: Session,
    *,
    team_specs: Sequence[tuple[str, str, str | None]],
    weeks: Mapping[int, Sequence[MatchupDTO]],
    regular_season_length: int,
) -> SeededLeague:
    """Sync a fake league, store its league-season settings, and return stored ids."""
    owners = [
        OwnerDTO(external_id=f"owner-{index}", display_name=f"Owner {name}")
        for index, (_, name, _) in enumerate(team_specs, start=1)
    ]
    teams = [
        TeamDTO(
            external_id=external_id,
            name=name,
            division=division,
            owner_external_id=f"owner-{index}",
        )
        for index, (external_id, name, division) in enumerate(team_specs, start=1)
    ]
    league = LeagueDTO(
        external_id=LEAGUE_EXTERNAL_ID,
        name="Test League",
        metadata={"regular_season_length": regular_season_length, "team_count": len(team_specs)},
    )
    week_status = WeekStatus(last_completed_week=max(weeks) if weeks else None)
    seed = {
        (LEAGUE_EXTERNAL_ID, SEASON): (
            league,
            owners,
            teams,
            {week: list(items) for week, items in weeks.items()},
            week_status,
        )
    }
    provider = FakeProvider(seed)
    summary = SyncService(provider, session).sync_league(
        LeagueRef(external_id=LEAGUE_EXTERNAL_ID), "fake", SEASON, weeks=sorted(weeks)
    )
    session.commit()

    repository = SyncRepository(session)
    stored_teams = repository.get_teams(summary.league_id, SEASON)
    return SeededLeague(
        league_id=summary.league_id,
        team_ids={team.external_id: team.id for team in stored_teams},
    )


def _four_team_weeks() -> dict[int, list[MatchupDTO]]:
    """Return a two-week, four-team schedule with distinct scores."""
    return {
        1: [
            _m(1, "team-a", "120.00", "team-d", "90.00"),
            _m(1, "team-b", "110.00", "team-c", "100.00"),
        ],
        2: [
            _m(2, "team-a", "130.00", "team-c", "95.00"),
            _m(2, "team-b", "105.00", "team-d", "115.00"),
        ],
    }


FOUR_TEAMS = (
    ("team-a", "Alpha", "East"),
    ("team-b", "Bravo", "East"),
    ("team-c", "Charlie", "West"),
    ("team-d", "Delta", "West"),
)


def _by_name(standings: Standings) -> dict[str, StandingRow]:
    """Index overall rows by team name for readable assertions."""
    return {row.team_name: row for row in standings.overall}


# ---------------------------------------------------------------------------
# AC-ST-01, AC-ST-02, AC-ST-07: exact season VP and overall ordering
# ---------------------------------------------------------------------------


def test_AC_ST_01_season_vp_is_exact_sum_of_weekly_vp(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_four_team_weeks(),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    rows = _by_name(standings)
    assert rows["Alpha"].weekly_vp == (Fraction(3), Fraction(3))
    assert rows["Bravo"].weekly_vp == (Fraction(2), Fraction(0))
    assert rows["Charlie"].weekly_vp == (Fraction(0), Fraction(-1))
    assert rows["Delta"].weekly_vp == (Fraction(-1), Fraction(2))
    assert rows["Alpha"].victory_points == Fraction(6)
    assert rows["Bravo"].victory_points == Fraction(2)
    assert rows["Charlie"].victory_points == Fraction(-1)
    assert rows["Delta"].victory_points == Fraction(1)
    for row in standings.overall:
        assert row.victory_points == sum(row.weekly_vp, Fraction(0))


def test_AC_ST_02_and_ST_07_overall_rank_is_across_the_whole_league(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_four_team_weeks(),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    assert standings.completed_weeks == 2
    assert [row.team_name for row in standings.overall] == [
        "Alpha",
        "Bravo",
        "Delta",
        "Charlie",
    ]
    assert [row.rank for row in standings.overall] == [1, 2, 3, 4]
    assert standings.overall[0].victory_points > standings.overall[1].victory_points


def test_rows_carry_owner_wins_losses_ties_and_points_for(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_four_team_weeks(),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    rows = _by_name(standings)
    assert rows["Alpha"].owner_name == "Owner Alpha"
    assert rows["Alpha"].division == "East"
    assert (rows["Alpha"].wins, rows["Alpha"].losses, rows["Alpha"].ties) == (2, 0, 0)
    assert (rows["Bravo"].wins, rows["Bravo"].losses, rows["Bravo"].ties) == (1, 1, 0)
    assert (rows["Charlie"].wins, rows["Charlie"].losses, rows["Charlie"].ties) == (0, 2, 0)
    assert (rows["Delta"].wins, rows["Delta"].losses, rows["Delta"].ties) == (1, 1, 0)
    assert rows["Alpha"].points_for == Decimal("250.00")
    assert rows["Bravo"].points_for == Decimal("215.00")
    assert rows["Charlie"].points_for == Decimal("195.00")
    assert rows["Delta"].points_for == Decimal("205.00")


# ---------------------------------------------------------------------------
# AC-ST-03, AC-ST-05: H2H tiebreak and shared ranks
# ---------------------------------------------------------------------------

SIX_TEAMS = (
    ("team-a", "Alpha", "East"),
    ("team-b", "Bravo", "North"),
    ("team-c", "Charlie", "East"),
    ("team-d", "Delta", "North"),
    ("team-e", "Echo", "West"),
    ("team-f", "Foxtrot", "West"),
)


def _h2h_tiebreak_weeks() -> dict[int, list[MatchupDTO]]:
    """Two weeks where VP ties are decided by H2H wins and then alphabetical order."""
    return {
        1: [
            _m(1, "team-a", "60.00", "team-f", "50.00"),
            _m(1, "team-b", "100.00", "team-c", "90.00"),
            _m(1, "team-d", "70.00", "team-e", "80.00"),
        ],
        2: [
            _m(2, "team-a", "80.00", "team-d", "70.00"),
            _m(2, "team-b", "50.00", "team-e", "60.00"),
            _m(2, "team-c", "90.00", "team-f", "100.00"),
        ],
    }


def test_AC_ST_03_vp_ties_are_ordered_by_h2h_wins(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=SIX_TEAMS,
        weeks=_h2h_tiebreak_weeks(),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    rows = _by_name(standings)
    assert rows["Alpha"].victory_points == Fraction(3)
    assert rows["Echo"].victory_points == Fraction(3)
    assert rows["Charlie"].victory_points == Fraction(2)
    # Charlie ties Bravo and Foxtrot on VP but has zero H2H wins, so ranks below them.
    assert rows["Charlie"].wins == 0
    assert rows["Bravo"].wins == 1
    assert rows["Foxtrot"].wins == 1
    assert [row.team_name for row in standings.overall] == [
        "Alpha",
        "Echo",
        "Bravo",
        "Foxtrot",
        "Charlie",
        "Delta",
    ]


# ---------------------------------------------------------------------------
# AC-ST-04 golden data: the points-for rule itself is owned by test_standings.py
# ---------------------------------------------------------------------------


POINTS_FOR_TEAMS = (
    ("team-a", "Alpha", None),
    ("team-b", "Bravo", None),
    ("team-c", "Charlie", None),
    ("team-d", "Delta", None),
    ("team-e", "Echo", None),
    ("team-f", "Foxtrot", None),
)


# ---------------------------------------------------------------------------
# AC-ST-06: divisions group overall-ranked rows and keep the overall rank
# ---------------------------------------------------------------------------


def test_AC_ST_06_divisions_group_the_same_overall_ranked_rows(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=SIX_TEAMS,
        weeks=_h2h_tiebreak_weeks(),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)
    overall_by_id = {row.team_id: row for row in standings.overall}

    assert [division.name for division in standings.divisions] == ["East", "North", "West"]
    for division in standings.divisions:
        for row in division.standings:
            # Same object/value as the overall table, including the overall rank.
            assert row is overall_by_id[row.team_id]
            assert row.rank == overall_by_id[row.team_id].rank
    east = next(division for division in standings.divisions if division.name == "East")
    west = next(division for division in standings.divisions if division.name == "West")
    assert [(row.team_name, row.rank) for row in east.standings] == [
        ("Alpha", 1),
        ("Charlie", 5),
    ]
    assert [(row.team_name, row.rank) for row in west.standings] == [
        ("Echo", 1),
        ("Foxtrot", 3),
    ]


def test_teams_without_a_division_group_last(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=POINTS_FOR_TEAMS,
        weeks={
            1: [
                _m(1, "team-a", "80.00", "team-d", "70.00"),
                _m(1, "team-b", "79.00", "team-e", "69.00"),
                _m(1, "team-c", "100.00", "team-f", "50.00"),
            ]
        },
        regular_season_length=1,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    assert standings.divisions == (DivisionStandings(name=None, standings=standings.overall),)


# ---------------------------------------------------------------------------
# Week filtering: playoffs, incomplete weeks, and the stored season bound
# ---------------------------------------------------------------------------


def _weeks_with_extra_week(extra_week: MatchupDTO) -> dict[int, list[MatchupDTO]]:
    weeks = _four_team_weeks()
    weeks[3] = [extra_week]
    return weeks


@pytest.mark.parametrize(
    ("is_playoff", "is_complete"),
    [
        pytest.param(True, True, id="playoff"),
        pytest.param(False, False, id="incomplete"),
    ],
)
def test_AC_ST_08_playoff_and_incomplete_weeks_contribute_no_vp_record_or_points(
    session: Session, is_playoff: bool, is_complete: bool
) -> None:
    """A playoff or incomplete week beyond the counted weeks keeps zero VP, record, and points."""
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_with_extra_week(
            _m(
                3,
                "team-a",
                "150.00",
                "team-b",
                "125.00",
                is_playoff=is_playoff,
                is_complete=is_complete,
            )
        ),
        regular_season_length=3,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    assert standings.completed_weeks == 2
    rows = _by_name(standings)
    assert rows["Alpha"].victory_points == Fraction(6)
    assert rows["Alpha"].wins == 2
    assert rows["Alpha"].points_for == Decimal("250.00")
    assert rows["Alpha"].weekly_vp == (Fraction(3), Fraction(3))


def test_regular_season_length_bounds_the_counted_weeks(session: Session) -> None:
    """A complete non-playoff week past league_season's length is excluded."""
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_weeks_with_extra_week(
            _m(3, "team-a", "150.00", "team-b", "125.00"),
        ),
        regular_season_length=2,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    assert standings.completed_weeks == 2
    rows = _by_name(standings)
    assert rows["Alpha"].victory_points == Fraction(6)
    assert rows["Alpha"].points_for == Decimal("250.00")
    assert len(rows["Alpha"].weekly_vp) == 2


# ---------------------------------------------------------------------------
# Byes and ties in the H2H record
# ---------------------------------------------------------------------------


def test_bye_week_has_no_h2h_result_but_keeps_rank_components(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks={
            1: [
                _m(1, "team-a", "140.00", None, None),
                _m(1, "team-b", "100.00", "team-c", "100.00"),
                _m(1, "team-d", "85.00", None, None),
            ]
        },
        regular_season_length=1,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    rows = _by_name(standings)
    # Alpha: highest score + top half, no opponent.
    assert rows["Alpha"].weekly_vp == (Fraction(2),)
    assert (rows["Alpha"].wins, rows["Alpha"].losses, rows["Alpha"].ties) == (0, 0, 0)
    # Bravo and Charlie tied each other: a tie for both and half top-half VP each.
    assert rows["Bravo"].weekly_vp == (Fraction(1),)
    assert rows["Charlie"].weekly_vp == (Fraction(1),)
    assert (rows["Bravo"].wins, rows["Bravo"].losses, rows["Bravo"].ties) == (0, 0, 1)
    assert (rows["Charlie"].wins, rows["Charlie"].losses, rows["Charlie"].ties) == (0, 0, 1)
    # Delta: lowest score, no opponent.
    assert rows["Delta"].weekly_vp == (Fraction(-1),)
    assert (rows["Delta"].wins, rows["Delta"].losses, rows["Delta"].ties) == (0, 0, 0)
    assert rows["Delta"].points_for == Decimal("85.00")
    # Bravo and Charlie share rank 2 (same VP, wins, and points for).
    assert rows["Bravo"].rank == rows["Charlie"].rank == 2
    assert rows["Alpha"].rank == 1
    assert rows["Delta"].rank == 4


# ---------------------------------------------------------------------------
# AC-ST-09: exact thirds are conserved
# ---------------------------------------------------------------------------


def test_AC_ST_09_thirds_are_exact_and_conserved(session: Session) -> None:
    weeks = {
        week: [
            _m(week, "team-a", "100.00", "team-d", "90.00"),
            _m(week, "team-b", "100.00", "team-e", "80.00"),
            _m(week, "team-c", "100.00", "team-f", "70.00"),
        ]
        for week in (1, 2, 3)
    }
    seeded = _seed(
        session,
        team_specs=SIX_TEAMS,
        weeks=weeks,
        regular_season_length=3,
    )

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)

    rows = _by_name(standings)
    tied = [rows[name] for name in ("Alpha", "Bravo", "Charlie")]
    for row in tied:
        # 1 H2H + 1 top-half + 1/3 high score each week, exactly.
        assert row.weekly_vp == (Fraction(7, 3), Fraction(7, 3), Fraction(7, 3))
        # Exact sums compare equal even when built from thirds.
        assert row.victory_points == Fraction(7)
    # Per week, the three high-score thirds conserve exactly one point.
    for week in range(3):
        shares = [row.weekly_vp[week] - Fraction(2) for row in tied]
        assert shares == [Fraction(1, 3), Fraction(1, 3), Fraction(1, 3)]
        assert sum(shares, Fraction(0)) == Fraction(1)
    assert rows["Delta"].victory_points == Fraction(0)
    assert rows["Foxtrot"].victory_points == Fraction(-3)


# ---------------------------------------------------------------------------
# AC-API-03: cumulative VP arithmetic
# ---------------------------------------------------------------------------


def test_AC_API_03_cumulative_is_the_running_exact_sum_of_weekly_vp(session: Session) -> None:
    weeks = {
        week: [
            _m(week, "team-a", "100.00", "team-d", "90.00"),
            _m(week, "team-b", "100.00", "team-e", "80.00"),
            _m(week, "team-c", "100.00", "team-f", "70.00"),
        ]
        for week in (1, 2, 3)
    }
    seeded = _seed(
        session,
        team_specs=SIX_TEAMS,
        weeks=weeks,
        regular_season_length=3,
    )

    history = StandingsService(session).get_vp_history(seeded.league_id, SEASON)

    assert history.weeks == (1, 2, 3)
    for team in history.teams:
        assert len(team.weekly) == len(team.cumulative) == 3
        running: list[Fraction] = []
        total = Fraction(0)
        for value in team.weekly:
            total += value
            running.append(total)
        assert team.cumulative == tuple(running)

    alpha = next(team for team in history.teams if team.team_name == "Alpha")
    assert alpha.weekly == (Fraction(7, 3), Fraction(7, 3), Fraction(7, 3))
    assert alpha.cumulative == (Fraction(7, 3), Fraction(14, 3), Fraction(7))

    standings = StandingsService(session).get_standings(seeded.league_id, SEASON)
    alpha_row = _by_name(standings)["Alpha"]
    assert alpha_row.victory_points == alpha.cumulative[-1]


def test_vp_history_excludes_playoff_and_incomplete_weeks(session: Session) -> None:
    weeks = _four_team_weeks()
    weeks[3] = [
        _m(3, "team-a", "150.00", "team-b", "125.00", is_playoff=True),
    ]
    weeks[4] = [
        _m(4, "team-a", "150.00", "team-b", "125.00", is_complete=False),
    ]
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=weeks,
        regular_season_length=4,
    )

    history = StandingsService(session).get_vp_history(seeded.league_id, SEASON)

    assert history.weeks == (1, 2)
    names = [team.team_name for team in history.teams]
    assert names == ["Alpha", "Bravo", "Charlie", "Delta"]
    alpha = next(team for team in history.teams if team.team_name == "Alpha")
    assert alpha.weekly == (Fraction(3), Fraction(3))
    assert alpha.cumulative == (Fraction(3), Fraction(6))


# ---------------------------------------------------------------------------
# Empty season and typed errors
# ---------------------------------------------------------------------------


def test_empty_season_returns_no_rows_and_no_weeks(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks={},
        regular_season_length=3,
    )

    service = StandingsService(session)
    standings = service.get_standings(seeded.league_id, SEASON)
    history = service.get_vp_history(seeded.league_id, SEASON)

    assert standings.completed_weeks == 0
    assert standings.overall == ()
    assert standings.divisions == ()
    assert history.weeks == ()
    assert history.teams == ()


def test_missing_league_raises_typed_error(session: Session) -> None:
    service = StandingsService(session)

    with pytest.raises(LeagueNotFoundError) as raised:
        service.get_standings(4242, SEASON)
    assert raised.value.league_id == 4242

    with pytest.raises(LeagueNotFoundError):
        service.get_vp_history(4242, SEASON)


def test_missing_season_raises_typed_error(session: Session) -> None:
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_four_team_weeks(),
        regular_season_length=2,
    )

    with pytest.raises(SeasonNotFoundError) as raised:
        StandingsService(session).get_standings(seeded.league_id, 1999)
    assert raised.value.league_id == seeded.league_id
    assert raised.value.season == 1999


def test_missing_teams_raises_typed_error(session: Session) -> None:
    repository = SyncRepository(session)
    league = repository.upsert_league("fake", "empty-league", "Empty", {}, "ref").row
    repository.upsert_league_season(league.id, SEASON, {"regular_season_length": 14})
    session.commit()

    with pytest.raises(TeamDataError):
        StandingsService(session).get_standings(league.id, SEASON)


def test_missing_week_score_raises_typed_error(session: Session) -> None:
    """A completed matchup whose score row is absent fails loudly instead of skewing VP."""
    seeded = _seed(
        session,
        team_specs=FOUR_TEAMS,
        weeks=_four_team_weeks(),
        regular_season_length=2,
    )
    repository = SyncRepository(session)
    away_team_id = seeded.team_ids["team-d"]
    away_score = next(
        score
        for score in repository.get_week_scores(seeded.league_id, SEASON, 1)
        if score.team_id == away_team_id
    )
    session.delete(away_score)
    session.flush()

    with pytest.raises(TeamDataError):
        StandingsService(session).get_standings(seeded.league_id, SEASON)


def test_missing_regular_season_length_raises_typed_error(session: Session) -> None:
    repository = SyncRepository(session)
    league = repository.upsert_league("fake", "no-settings", "No Settings", {}, "ref").row
    repository.upsert_league_season(league.id, SEASON, {"team_count": 12})
    session.commit()

    with pytest.raises(SeasonSettingsError):
        StandingsService(session).get_standings(league.id, SEASON)
