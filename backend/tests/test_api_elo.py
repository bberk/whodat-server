"""HTTP acceptance tests for Elo history and settings (AC-Elo-*).

The tests build an isolated SQLite database, seed it through the real sync service and
``FakeProvider``, and drive the application with ``TestClient``. They assert the authorization
matrix, structured error bodies, string serialization of every rating, config defaults and
validation, and the empty-history case. No test calls ESPN.
"""

from __future__ import annotations

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

LEAGUE_EXTERNAL = "elo-api-fixture"
SEASON = 2026


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
        engine = create_engine(f"sqlite:///{tmp_path / f'elo-{len(engines)}.db'}")
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


def matchup(
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


def seed_league(
    api: Api,
    *,
    weeks: Mapping[int, Sequence[MatchupDTO]] | None = None,
    regular_season_length: int = 2,
) -> int:
    """Sync a two-team fake league and return its stored id."""
    schedule = weeks or {
        1: [matchup(1, "team-a", "120", "team-b", "100")],
        2: [matchup(2, "team-b", "130", "team-a", "90")],
    }
    owners = [
        OwnerDTO(external_id="owner-a", display_name="Owner Alpha"),
        OwnerDTO(external_id="owner-b", display_name="Owner Bravo"),
    ]
    teams = [
        TeamDTO(
            external_id="team-a",
            name="Alpha",
            division="East",
            owner_external_id="owner-a",
        ),
        TeamDTO(
            external_id="team-b",
            name="Bravo",
            division="West",
            owner_external_id="owner-b",
        ),
    ]
    league = LeagueDTO(
        external_id=LEAGUE_EXTERNAL,
        name="Elo API League",
        metadata={
            "regular_season_length": regular_season_length,
            "team_count": len(teams),
        },
    )
    seed = {
        (LEAGUE_EXTERNAL, SEASON): (
            league,
            owners,
            teams,
            {week: list(items) for week, items in schedule.items()},
            WeekStatus(last_completed_week=max(schedule)),
        )
    }
    with api.factory() as session:
        summary = SyncService(FakeProvider(seed), session).sync_league(
            LeagueRef(external_id=LEAGUE_EXTERNAL),
            "fake",
            SEASON,
            weeks=sorted(schedule),
        )
        session.commit()
        return summary.league_id


def create_user(api: Api, email: str, *, league_id: int | None, role: str = "member") -> int:
    """Create an account with a role and optionally its league membership."""
    with api.factory() as session:
        user = UserRepository(session).create(email, "unused-password-hash")
        user.role = role
        if league_id is not None:
            MembershipRepository(session).create(user.id, league_id)
        session.commit()
        return user.id


def login(api: Api, user_id: int) -> None:
    """Attach a valid signed session cookie for ``user_id`` to the test client."""
    response = Response()
    set_session(response, user_id)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)


def history_path(league_id: int, mode: str | None = None) -> str:
    """Return the history URL, optionally with a mode query parameter."""
    base = f"/api/v1/leagues/{league_id}/elo-history"
    return base if mode is None else f"{base}?mode={mode}"


def config_path(league_id: int) -> str:
    """Return the settings URL."""
    return f"/api/v1/leagues/{league_id}/elo-config"


def valid_config() -> dict[str, str]:
    """Return a valid settings payload."""
    return {
        "starting_rating": "1500",
        "k_factor": "24",
        "margin_weight": "0.25",
        "margin_cap": "50",
        "season_regression": "0.333333",
    }


# ---------------------------------------------------------------------------
# Authorization and error shapes
# ---------------------------------------------------------------------------


def test_AC_Elo_42_history_requires_auth_and_membership(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)

    unauthenticated = api.client.get(history_path(league_id))
    assert unauthenticated.status_code == 401

    login(api, create_user(api, "outsider@example.com", league_id=None))
    outsider = api.client.get(history_path(league_id))
    unknown = api.client.get(history_path(999))
    assert outsider.status_code == 404
    assert outsider.json()["detail"]["code"] == "not_found"
    assert unknown.status_code == 404


def test_AC_Elo_43_history_returns_both_modes_with_decimal_strings(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)
    login(api, create_user(api, "member@example.com", league_id=league_id))

    actual = api.client.get(history_path(league_id, "actual_schedule"))
    round_robin = api.client.get(history_path(league_id, "round_robin"))

    assert actual.status_code == 200
    assert round_robin.status_code == 200
    body = actual.json()
    assert body["mode"] == "actual_schedule"
    assert body["seasons"] == [SEASON]
    assert [week["week"] for week in body["weeks"]] == [1, 2]
    assert body["config"]["starting_rating"] == "1500"
    assert body["config"]["k_factor"] == "24"
    assert body["config"]["season_regression"] == "0.333333"
    for team in body["teams"]:
        assert len(team["series"]) == 2
        assert all(value is None or isinstance(value, str) for value in team["series"])
        assert isinstance(team["current"], str)
        assert isinstance(team["last_change"], str)
        assert isinstance(team["season_change"], str)
        assert isinstance(team["peak"], str)
        assert isinstance(team["low"], str)
        assert team["current"] == team["series"][-1]
    assert round_robin.json()["mode"] == "round_robin"


def test_AC_Elo_44_invalid_mode_and_league_id_are_structured_422(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)
    login(api, create_user(api, "member@example.com", league_id=league_id))

    invalid_mode = api.client.get(history_path(league_id, "not-a-mode"))
    negative = api.client.get(history_path(-1))

    assert invalid_mode.status_code == 422
    assert isinstance(invalid_mode.json()["detail"], list)
    assert negative.status_code == 422
    assert isinstance(negative.json()["detail"], list)


def test_AC_Elo_45_config_requires_admin_and_returns_defaults(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)

    assert api.client.get(config_path(league_id)).status_code == 401

    login(api, create_user(api, "member@example.com", league_id=league_id))
    assert api.client.get(config_path(league_id)).status_code == 403

    api = api_factory()
    league_id = seed_league(api)
    login(api, create_user(api, "admin@example.com", league_id=league_id, role="admin"))
    response = api.client.get(config_path(league_id))

    assert response.status_code == 200
    assert response.json() == {
        "league_id": league_id,
        "starting_rating": "1500",
        "k_factor": "24",
        "margin_weight": "0.25",
        "margin_cap": "50",
        "season_regression": "0.333333",
    }


def test_AC_Elo_46_config_put_persists_and_validates(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)
    login(api, create_user(api, "admin@example.com", league_id=league_id, role="admin"))

    payload = {
        "starting_rating": "1600",
        "k_factor": "32",
        "margin_weight": "0.5",
        "margin_cap": "40",
        "season_regression": "0.5",
    }
    saved = api.client.put(config_path(league_id), json=payload)
    assert saved.status_code == 200
    assert saved.json()["starting_rating"] == "1600"
    assert saved.json()["k_factor"] == "32"

    fetched = api.client.get(config_path(league_id))
    assert fetched.json()["margin_weight"] == "0.5"
    assert fetched.json()["season_regression"] == "0.5"

    invalid = api.client.put(config_path(league_id), json={**payload, "starting_rating": "999"})
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)

    negative = api.client.put(config_path(-4), json=payload)
    assert negative.status_code == 422


def test_AC_Elo_47_config_put_is_forbidden_for_a_member(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)
    login(api, create_user(api, "member@example.com", league_id=league_id))

    response = api.client.put(config_path(league_id), json=valid_config())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_AC_Elo_48_empty_history_is_200_with_empty_arrays(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    with api.factory() as session:
        league = (
            SyncRepository(session)
            .upsert_league("fake", "empty-one", "Empty", {}, "membership")
            .row
        )
        session.commit()
        league_id = league.id
    login(api, create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(history_path(league_id))

    assert response.status_code == 200
    body = response.json()
    assert body["weeks"] == []
    assert body["teams"] == []
    assert body["season_boundaries"] == []
    assert body["warnings"] == []


def test_AC_Elo_49_history_never_returns_credential_material(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = seed_league(api)
    user_id = create_user(api, "member@example.com", league_id=league_id)
    with api.factory() as session:
        MembershipRepository(session).set_credentials(
            user_id,
            league_id,
            espn_s2_encrypted="secret-espn-s2-token",
            espn_swid_encrypted="secret-espn-swid-token",
        )
        session.commit()
    login(api, user_id)

    response = api.client.get(history_path(league_id))

    assert response.status_code == 200
    assert "secret-espn" not in response.text
    assert "espn_s2" not in response.text
    assert "password" not in response.text.lower()
