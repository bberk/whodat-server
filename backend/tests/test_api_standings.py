"""HTTP acceptance tests for the standings and VP-history routes.

Each test builds a temporary SQLite database, seeds a league through the real sync service and
:class:`~app.providers.fake.FakeProvider`, and drives the application through ``TestClient``. No
test calls ESPN or any other network service. The standings golden comparison is checked in here
as JSON so AC-API-02 fails if the wire shape, ranks, or serialized numbers drift.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.main import create_app
from app.api.session import SESSION_COOKIE_NAME, set_session
from app.db.auth_repositories import MembershipRepository, UserRepository
from app.db.base import Base
from app.db.repositories import SyncRepository
from app.db.session import get_session as db_get_session
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
from app.services.sync_service import SyncService

SEASON = 2026
LEAGUE_EXTERNAL = "standings-fixture-league"
OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"

FOUR_TEAMS = (
    ("team-a", "Alpha", "East"),
    ("team-b", "Bravo", "East"),
    ("team-c", "Charlie", "West"),
    ("team-d", "Delta", "West"),
)

SIX_TEAMS = (
    ("team-a", "Alpha", "East"),
    ("team-b", "Bravo", "North"),
    ("team-c", "Charlie", "East"),
    ("team-d", "Delta", "North"),
    ("team-e", "Echo", "West"),
    ("team-f", "Foxtrot", "West"),
)

#: Exact wire payload for the two-week, four-team fixture league (AC-API-02). The ids are stable
#: because every test starts from an empty database and sync inserts leagues, owners, then teams.
GOLDEN_STANDINGS = json.loads(
    """
    {
      "league_id": 1,
      "season": 2026,
      "completed_weeks": 2,
      "overall": [
        {
          "rank": 1,
          "team_id": 1,
          "team_name": "Alpha",
          "owner_name": "Owner Alpha",
          "division": "East",
          "victory_points": "6",
          "wins": 2,
          "losses": 0,
          "ties": 0,
          "points_for": "250",
          "weekly_vp": ["3", "3"],
          "clinch": null
        },
        {
          "rank": 2,
          "team_id": 2,
          "team_name": "Bravo",
          "owner_name": "Owner Bravo",
          "division": "East",
          "victory_points": "2",
          "wins": 1,
          "losses": 1,
          "ties": 0,
          "points_for": "215",
          "weekly_vp": ["2", "0"],
          "clinch": null
        },
        {
          "rank": 3,
          "team_id": 4,
          "team_name": "Delta",
          "owner_name": "Owner Delta",
          "division": "West",
          "victory_points": "1",
          "wins": 1,
          "losses": 1,
          "ties": 0,
          "points_for": "205",
          "weekly_vp": ["-1", "2"],
          "clinch": null
        },
        {
          "rank": 4,
          "team_id": 3,
          "team_name": "Charlie",
          "owner_name": "Owner Charlie",
          "division": "West",
          "victory_points": "-1",
          "wins": 0,
          "losses": 2,
          "ties": 0,
          "points_for": "195",
          "weekly_vp": ["0", "-1"],
          "clinch": null
        }
      ],
      "divisions": [
        {
          "name": "East",
          "standings": [
            {
              "rank": 1,
              "team_id": 1,
              "team_name": "Alpha",
              "owner_name": "Owner Alpha",
              "division": "East",
              "victory_points": "6",
              "wins": 2,
              "losses": 0,
              "ties": 0,
              "points_for": "250",
              "weekly_vp": ["3", "3"],
              "clinch": null
            },
            {
              "rank": 2,
              "team_id": 2,
              "team_name": "Bravo",
              "owner_name": "Owner Bravo",
              "division": "East",
              "victory_points": "2",
              "wins": 1,
              "losses": 1,
              "ties": 0,
              "points_for": "215",
              "weekly_vp": ["2", "0"],
              "clinch": null
            }
          ]
        },
        {
          "name": "West",
          "standings": [
            {
              "rank": 3,
              "team_id": 4,
              "team_name": "Delta",
              "owner_name": "Owner Delta",
              "division": "West",
              "victory_points": "1",
              "wins": 1,
              "losses": 1,
              "ties": 0,
              "points_for": "205",
              "weekly_vp": ["-1", "2"],
              "clinch": null
            },
            {
              "rank": 4,
              "team_id": 3,
              "team_name": "Charlie",
              "owner_name": "Owner Charlie",
              "division": "West",
              "victory_points": "-1",
              "wins": 0,
              "losses": 2,
              "ties": 0,
              "points_for": "195",
              "weekly_vp": ["0", "-1"],
              "clinch": null
            }
          ]
        }
      ]
    }
    """
)


@dataclass
class Api:
    """A test application and the database session factory it reads from."""

    client: TestClient
    factory: sessionmaker[Session]


@pytest.fixture
def api_factory(tmp_path: Path) -> Iterator[Callable[[], Api]]:
    """Build isolated applications so tests never share database state."""
    engines: list[Engine] = []

    def build() -> Api:
        engine = create_engine(f"sqlite:///{tmp_path / f'standings-{len(engines)}.db'}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        app = create_app()

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        app.dependency_overrides[db_get_session] = override_session
        return Api(client=TestClient(app), factory=factory)

    try:
        yield build
    finally:
        for engine in engines:
            Base.metadata.drop_all(engine)
            engine.dispose()


def _matchup(
    week: int,
    home: str,
    home_points: str,
    away: str,
    away_points: str,
) -> MatchupDTO:
    """Build one completed regular-season matchup."""
    return MatchupDTO(
        week=week,
        home=MatchupSideDTO(team_external_id=home, points=Decimal(home_points)),
        away=MatchupSideDTO(team_external_id=away, points=Decimal(away_points)),
        is_playoff=False,
        is_complete=True,
    )


def _fixture_weeks() -> dict[int, list[MatchupDTO]]:
    """Return the two-week fixture schedule used by the golden comparison."""
    return {
        1: [
            _matchup(1, "team-a", "120.00", "team-d", "90.00"),
            _matchup(1, "team-b", "110.00", "team-c", "100.00"),
        ],
        2: [
            _matchup(2, "team-a", "130.00", "team-c", "95.00"),
            _matchup(2, "team-b", "105.00", "team-d", "115.00"),
        ],
    }


def _six_week_fixture() -> dict[int, list[MatchupDTO]]:
    """Return a six-week, four-team schedule so period 2 is offered and current."""
    weeks = _fixture_weeks()
    weeks.update(
        {
            3: [
                _matchup(3, "team-a", "100.00", "team-d", "80.00"),
                _matchup(3, "team-b", "90.00", "team-c", "70.00"),
            ],
            4: [
                _matchup(4, "team-a", "110.00", "team-c", "85.00"),
                _matchup(4, "team-b", "95.00", "team-d", "105.00"),
            ],
            5: [
                _matchup(5, "team-a", "120.00", "team-d", "90.00"),
                _matchup(5, "team-b", "110.00", "team-c", "100.00"),
            ],
            6: [
                _matchup(6, "team-a", "130.00", "team-c", "95.00"),
                _matchup(6, "team-b", "105.00", "team-d", "115.00"),
            ],
        }
    )
    return weeks


def _thirds_weeks() -> dict[int, list[MatchupDTO]]:
    """Return three weeks where three teams split the high-score point as exact thirds."""
    return {
        week: [
            _matchup(week, "team-a", "100.00", "team-d", "90.00"),
            _matchup(week, "team-b", "100.00", "team-e", "80.00"),
            _matchup(week, "team-c", "100.00", "team-f", "70.00"),
        ]
        for week in (1, 2, 3)
    }


def _seed_league(
    api: Api,
    *,
    team_specs: Sequence[tuple[str, str, str | None]],
    weeks: Mapping[int, Sequence[MatchupDTO]],
    regular_season_length: int,
    playoff_team_count: int | None = None,
    season: int = SEASON,
    external_id: str = LEAGUE_EXTERNAL,
) -> int:
    """Sync a fake league and its league-season settings into the test database."""
    owners = [
        OwnerDTO(external_id=f"owner-{index}", display_name=f"Owner {name}")
        for index, (_, name, _) in enumerate(team_specs, start=1)
    ]
    teams = [
        TeamDTO(
            external_id=external_id_name,
            name=name,
            division=division,
            owner_external_id=f"owner-{index}",
        )
        for index, (external_id_name, name, division) in enumerate(team_specs, start=1)
    ]
    metadata: dict[str, object] = {
        "regular_season_length": regular_season_length,
        "team_count": len(team_specs),
    }
    if playoff_team_count is not None:
        metadata["playoff_team_count"] = playoff_team_count
    league = LeagueDTO(
        external_id=external_id,
        name="Standings Fixture League",
        metadata=metadata,
    )
    seed = {
        (external_id, season): (
            league,
            owners,
            teams,
            {week: list(items) for week, items in weeks.items()},
            WeekStatus(last_completed_week=max(weeks) if weeks else None),
        )
    }
    with api.factory() as session:
        summary = SyncService(FakeProvider(seed), session).sync_league(
            LeagueRef(external_id=external_id),
            "fake",
            season,
            weeks=sorted(weeks),
        )
        session.commit()
        return summary.league_id


def _seed_bare_season(api: Api) -> int:
    """Store a league season with no settings, so standings cannot be produced."""
    with api.factory() as session:
        repository = SyncRepository(session)
        league = repository.upsert_league("fake", "bare-league", "Bare", {}, "ref").row
        repository.upsert_league_season(league.id, SEASON, {})
        session.commit()
        return league.id


def _create_user(api: Api, email: str, *, league_id: int | None = None) -> int:
    """Create an account and optionally its membership in ``league_id``."""
    with api.factory() as session:
        user = UserRepository(session).create(email, "unused-password-hash")
        if league_id is not None:
            MembershipRepository(session).create(user.id, league_id)
        session.commit()
        return user.id


def _login(api: Api, user_id: int) -> None:
    """Attach a valid signed session cookie for ``user_id`` to the test client."""
    response = Response()
    set_session(response, user_id)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)


def _standings_path(league_id: int, season: int = SEASON) -> str:
    """Return the standings URL for a league season."""
    return f"/api/v1/leagues/{league_id}/seasons/{season}/standings"


def _history_path(league_id: int, season: int = SEASON) -> str:
    """Return the VP-history URL for a league season."""
    return f"/api/v1/leagues/{league_id}/seasons/{season}/vp-history"


def _wapdate_path(league_id: int, season: int = SEASON) -> str:
    """Return the WAPDate URL for a league season."""
    return f"/api/v1/leagues/{league_id}/seasons/{season}/wapdate"


# ---------------------------------------------------------------------------
# AC-API-02: golden standings response
# ---------------------------------------------------------------------------


def test_AC_API_02_standings_match_the_golden_json(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    response = api.client.get(_standings_path(league_id))

    assert response.status_code == 200
    assert response.json() == GOLDEN_STANDINGS


def test_AC_PC_11_standings_api_serializes_each_clinch_status(
    api_factory: Callable[[], Api],
) -> None:
    """A stored playoff field size puts the same badge on overall and division rows."""
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
        playoff_team_count=4,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    response = api.client.get(_standings_path(league_id))

    assert response.status_code == 200
    payload = response.json()
    assert {row["team_name"]: row["clinch"] for row in payload["overall"]} == {
        "Alpha": "Z",
        "Bravo": "X",
        "Charlie": "X",
        "Delta": "Y",
    }
    assert {
        row["team_name"]: row["clinch"]
        for division in payload["divisions"]
        for row in division["standings"]
    } == {
        "Alpha": "Z",
        "Bravo": "X",
        "Delta": "Y",
        "Charlie": "X",
    }


# ---------------------------------------------------------------------------
# AC-ST-06/07: overall rank ordering and division rows keeping the overall rank
# ---------------------------------------------------------------------------


def test_AC_ST_06_division_rows_keep_the_overall_rank(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    body = api.client.get(_standings_path(league_id)).json()
    overall_rank = {row["team_id"]: row["rank"] for row in body["overall"]}

    assert [row["team_name"] for row in body["overall"]] == [
        "Alpha",
        "Bravo",
        "Delta",
        "Charlie",
    ]
    assert [row["rank"] for row in body["overall"]] == [1, 2, 3, 4]
    assert [division["name"] for division in body["divisions"]] == ["East", "West"]
    for division in body["divisions"]:
        for row in division["standings"]:
            assert row["rank"] == overall_rank[row["team_id"]]
    east = next(division for division in body["divisions"] if division["name"] == "East")
    assert [(row["team_name"], row["rank"]) for row in east["standings"]] == [
        ("Alpha", 1),
        ("Bravo", 2),
    ]


# ---------------------------------------------------------------------------
# AC-API-03: cumulative VP arithmetic
# ---------------------------------------------------------------------------


def test_AC_API_03_cumulative_equals_the_running_sum_of_weekly_vp(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    response = api.client.get(_history_path(league_id))

    assert response.status_code == 200
    body = response.json()
    assert body["weeks"] == [1, 2]
    for team in body["teams"]:
        running: list[Decimal] = []
        total = Decimal(0)
        for value in team["weekly"]:
            total += Decimal(value)
            running.append(total)
        assert team["cumulative"] == [format(value, "f") for value in running]


def test_AC_API_03_weekly_vp_is_trimmed_to_two_decimals(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=SIX_TEAMS,
        weeks=_thirds_weeks(),
        regular_season_length=3,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    body = api.client.get(_history_path(league_id)).json()

    alpha = next(team for team in body["teams"] if team["team_name"] == "Alpha")
    assert alpha["weekly"] == ["2.33", "2.33", "2.33"]
    assert alpha["cumulative"] == ["2.33", "4.67", "7"]


# ---------------------------------------------------------------------------
# AC-WD-*: WAPDate periods, ordering, cup week, greying, and serialization
# ---------------------------------------------------------------------------


def test_AC_WD_02_week_six_offers_period_one_complete_and_period_two_current(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_six_week_fixture(),
        regular_season_length=8,
    )
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(_wapdate_path(league_id))

    assert response.status_code == 200
    body = response.json()
    assert body["highest_completed_week"] == 6
    assert [
        (
            period["period"],
            period["start_week"],
            period["end_week"],
            period["status"],
            period["weeks"],
        )
        for period in body["periods"]
    ] == [
        (1, 1, 4, "complete", [1, 2, 3, 4]),
        (2, 5, 8, "current", [5, 6]),
    ]


def test_AC_WD_07_wapdate_serializes_period_totals_as_exact_strings(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_six_week_fixture(),
        regular_season_length=8,
    )
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    body = api.client.get(_wapdate_path(league_id)).json()
    first, second = body["periods"]

    assert [row["team_name"] for row in first["rows"]] == [
        "Charlie",
        "Delta",
        "Bravo",
        "Alpha",
    ]
    assert [row["team_name"] for row in second["rows"]] == [
        "Charlie",
        "Delta",
        "Bravo",
        "Alpha",
    ]
    alpha = next(row for row in first["rows"] if row["team_name"] == "Alpha")
    assert alpha == {
        "team_id": 1,
        "team_name": "Alpha",
        "victory_points": "12",
        "wins": 4,
        "points_for": "460",
        "eliminated": False,
    }
    current_alpha = next(row for row in second["rows"] if row["team_name"] == "Alpha")
    assert current_alpha["victory_points"] == "6"
    assert current_alpha["wins"] == 2
    assert current_alpha["points_for"] == "250"
    assert isinstance(alpha["victory_points"], str)
    assert isinstance(alpha["points_for"], str)


def test_AC_WD_03_cup_week_removes_period_wins_but_keeps_points_for_and_vp(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_six_week_fixture(),
        regular_season_length=8,
    )
    with api.factory() as session:
        league_season = SyncRepository(session).get_league_season(league_id, SEASON)
        assert league_season is not None
        league_season.cup_week = 6
        session.commit()
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    body = api.client.get(_wapdate_path(league_id)).json()
    current = next(period for period in body["periods"] if period["period"] == 2)

    assert {
        row["team_name"]: (row["victory_points"], row["wins"], row["points_for"])
        for row in current["rows"]
    } == {
        "Charlie": ("-1", 0, "195"),
        "Delta": ("0", 0, "205"),
        "Bravo": ("2", 1, "215"),
        "Alpha": ("5", 1, "250"),
    }


def test_AC_WD_05_current_period_greys_only_teams_that_cannot_finish_last(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks={
            1: [
                _matchup(1, "team-a", "120.00", "team-d", "90.00"),
                _matchup(1, "team-b", "110.00", "team-c", "100.00"),
            ],
            2: [
                _matchup(2, "team-a", "130.00", "team-d", "80.00"),
                _matchup(2, "team-b", "100.00", "team-c", "90.00"),
            ],
        },
        regular_season_length=8,
    )
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    body = api.client.get(_wapdate_path(league_id)).json()
    period = body["periods"][0]

    assert period["status"] == "current"
    assert {row["team_name"]: row["eliminated"] for row in period["rows"]} == {
        "Charlie": False,
        "Delta": False,
        "Bravo": False,
        "Alpha": True,
    }


def test_AC_WD_06_completed_period_has_no_greying(api_factory: Callable[[], Api]) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_six_week_fixture(),
        regular_season_length=8,
    )
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    body = api.client.get(_wapdate_path(league_id)).json()
    first = next(period for period in body["periods"] if period["period"] == 1)

    assert first["status"] == "complete"
    assert all(row["eliminated"] is False for row in first["rows"])


def test_AC_WD_07_empty_season_has_no_wapdate_periods(api_factory: Callable[[], Api]) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks={},
        regular_season_length=3,
    )
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(_wapdate_path(league_id))

    assert response.status_code == 200
    assert response.json() == {
        "league_id": league_id,
        "season": SEASON,
        "highest_completed_week": None,
        "periods": [],
    }


# ---------------------------------------------------------------------------
# AC-API-04: structured 4xx for invalid input, never a 500
# ---------------------------------------------------------------------------


SEASON_PATHS = {
    "standings": _standings_path,
    "history": _history_path,
    "wapdate": _wapdate_path,
}


@pytest.mark.parametrize("path_kind", ["standings", "history", "wapdate"])
def test_AC_API_04_unknown_season_returns_structured_404(
    api_factory: Callable[[], Api], path_kind: str
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    response = api.client.get(SEASON_PATHS[path_kind](league_id, 2025))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


@pytest.mark.parametrize("path_kind", ["standings", "history", "wapdate"])
def test_AC_API_04_invalid_season_settings_return_structured_400(
    api_factory: Callable[[], Api], path_kind: str
) -> None:
    api = api_factory()
    league_id = _seed_bare_season(api)
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    response = api.client.get(SEASON_PATHS[path_kind](league_id))

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "standings_unavailable"
    assert "regular_season_length" not in response.text


def test_empty_season_returns_empty_standings_and_history(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks={},
        regular_season_length=3,
    )
    user_id = _create_user(api, "member@example.com", league_id=league_id)
    _login(api, user_id)

    standings = api.client.get(_standings_path(league_id))
    history = api.client.get(_history_path(league_id))

    assert standings.status_code == 200
    assert standings.json() == {
        "league_id": league_id,
        "season": SEASON,
        "completed_weeks": 0,
        "overall": [],
        "divisions": [],
    }
    assert history.status_code == 200
    assert history.json() == {"weeks": [], "teams": []}


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path_kind", ["standings", "history", "wapdate"])
def test_AC_AU_10_unauthenticated_requests_return_401(
    api_factory: Callable[[], Api], path_kind: str
) -> None:
    api = api_factory()

    response = api.client.get(SEASON_PATHS[path_kind](1))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


@pytest.mark.parametrize("path_kind", ["standings", "history", "wapdate"])
def test_AC_AU_10_non_member_and_unknown_league_return_404(
    api_factory: Callable[[], Api], path_kind: str
) -> None:
    api = api_factory()
    league_id = _seed_league(
        api,
        team_specs=FOUR_TEAMS,
        weeks=_fixture_weeks(),
        regular_season_length=2,
    )
    _login(api, _create_user(api, "outsider@example.com"))
    path = SEASON_PATHS[path_kind]

    non_member = api.client.get(path(league_id))
    unknown = api.client.get(path(999))

    assert non_member.status_code == 404
    assert non_member.json()["detail"]["code"] == "not_found"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# AC-API-01: committed OpenAPI export matches the application
# ---------------------------------------------------------------------------


def test_AC_API_01_openapi_export_is_current() -> None:
    expected = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    document = json.loads(expected)

    assert "/api/v1/leagues/{league_id}/seasons/{season}/standings" in document["paths"]
    assert "/api/v1/leagues/{league_id}/seasons/{season}/vp-history" in document["paths"]
    assert "/api/v1/leagues/{league_id}/seasons/{season}/wapdate" in document["paths"]
    assert "/api/v1/leagues/{league_id}/seasons/settings" in document["paths"]
    assert "/api/v1/leagues/{league_id}/elo-history" in document["paths"]
    assert "/api/v1/leagues/{league_id}/elo-config" in document["paths"]
    assert "/api/v1/leagues/{league_id}/seasons/{season}/refresh" in document["paths"]
    assert "delete" in document["paths"]["/api/v1/leagues/{league_id}/seasons/{season}"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/seasons/settings"]
    assert "post" in document["paths"]["/api/v1/leagues/{league_id}/seasons/{season}/refresh"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/seasons/{season}/standings"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/seasons/{season}/vp-history"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/seasons/{season}/wapdate"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/elo-history"]
    assert "get" in document["paths"]["/api/v1/leagues/{league_id}/elo-config"]
    assert "put" in document["paths"]["/api/v1/leagues/{league_id}/elo-config"]
    assert OPENAPI_PATH.read_text(encoding="utf-8") == expected
