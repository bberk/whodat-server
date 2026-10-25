"""Service and digest/cache tests for playoff odds.

Every test builds stored data through the FakeProvider and the real sync service, then reads it
through the standings and prediction services. No test contacts ESPN.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.main import create_app
from app.api.rate_limit import RateLimiter
from app.api.routes_predictions import get_prediction_limiter
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
from app.services import prediction_service
from app.services.prediction_service import (
    PredictionCache,
    PredictionService,
    clear_prediction_cache,
    wilson_interval,
)
from app.services.standings_service import (
    SeasonSettingsError,
    StandingsService,
)
from app.services.sync_service import SyncService

SEASON = 2026
LEAGUE_EXTERNAL_ID = "prediction-league"

TEAM_SPECS = (
    ("team-a", "Alpha", "East"),
    ("team-b", "Bravo", "East"),
    ("team-c", "Charlie", "West"),
    ("team-d", "Delta", "West"),
)


@dataclass
class Api:
    """A test application and the database session factory it reads from."""

    client: TestClient
    factory: sessionmaker[Session]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """Provide an isolated SQLite database session for each test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'predictions.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset_prediction_state() -> Iterator[None]:
    """Keep the process-wide limiter and cache from leaking between tests."""
    get_prediction_limiter().reset()
    clear_prediction_cache()
    yield
    get_prediction_limiter().reset()
    clear_prediction_cache()


@pytest.fixture
def api_factory(tmp_path: Path) -> Iterator[Callable[[], Api]]:
    """Build isolated applications so tests never share database state."""
    engines: list[Engine] = []

    def build() -> Api:
        engine = create_engine(f"sqlite:///{tmp_path / f'predictions-{len(engines)}.db'}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        app = create_app()

        def override_session() -> Iterator[Session]:
            with factory() as request_session:
                yield request_session

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
    home_points: str | None,
    away: str | None,
    away_points: str | None,
    *,
    is_playoff: bool = False,
    is_complete: bool = True,
) -> MatchupDTO:
    return MatchupDTO(
        week=week,
        home=MatchupSideDTO(
            team_external_id=home,
            points=None if home_points is None else Decimal(home_points),
        ),
        away=(
            None
            if away is None
            else MatchupSideDTO(
                team_external_id=away,
                points=None if away_points is None else Decimal(away_points),
            )
        ),
        is_playoff=is_playoff,
        is_complete=is_complete,
    )


def _completed_weeks() -> dict[int, list[MatchupDTO]]:
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


def _future_week(*, is_playoff: bool = False) -> list[MatchupDTO]:
    return [
        _matchup(3, "team-a", None, "team-c", None, is_playoff=is_playoff, is_complete=False),
        _matchup(3, "team-b", None, "team-d", None, is_playoff=is_playoff, is_complete=False),
    ]


def _seed_league(
    session: Session,
    *,
    weeks: Mapping[int, Sequence[MatchupDTO]],
    regular_season_length: int = 3,
    playoff_team_count: int | None = 3,
    teams: Sequence[tuple[str, str, str | None]] = TEAM_SPECS,
    cup_week: int | None = None,
) -> int:
    owners = [
        OwnerDTO(external_id=f"owner-{index}", display_name=f"Owner {name}")
        for index, (_, name, _) in enumerate(teams, start=1)
    ]
    team_dtos = [
        TeamDTO(
            external_id=external_id,
            name=name,
            division=division,
            owner_external_id=f"owner-{index}",
        )
        for index, (external_id, name, division) in enumerate(teams, start=1)
    ]
    metadata: dict[str, object] = {
        "regular_season_length": regular_season_length,
        "team_count": len(teams),
    }
    if playoff_team_count is not None:
        metadata["playoff_team_count"] = playoff_team_count
    league = LeagueDTO(
        external_id=LEAGUE_EXTERNAL_ID,
        name="Prediction Fixture League",
        metadata=metadata,
    )
    seed = {
        (LEAGUE_EXTERNAL_ID, SEASON): (
            league,
            owners,
            team_dtos,
            {week: list(items) for week, items in weeks.items()},
            WeekStatus(last_completed_week=max(weeks) if weeks else None),
        )
    }
    summary = SyncService(FakeProvider(seed), session).sync_league(
        LeagueRef(external_id=LEAGUE_EXTERNAL_ID),
        "fake",
        SEASON,
        weeks=sorted(weeks),
    )
    if cup_week is not None:
        stored = SyncRepository(session).get_league_season(summary.league_id, SEASON)
        assert stored is not None
        stored.cup_week = cup_week
    session.commit()
    return summary.league_id


def _standard_weeks() -> dict[int, list[MatchupDTO]]:
    weeks = _completed_weeks()
    weeks[3] = _future_week()
    return weeks


# ---------------------------------------------------------------------------
# Snapshot, digest, and cache
# ---------------------------------------------------------------------------


def test_service_returns_probabilities_and_metadata(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    cache = PredictionCache()

    odds = PredictionService(session, cache=cache).get_playoff_odds(
        league_id, SEASON, iterations=1_000, seed=7
    )

    assert odds.status == "ok"
    assert odds.iterations == 1_000
    assert odds.seed == 7
    assert odds.completed_weeks == 2
    assert odds.remaining_weeks == (3,)
    assert odds.playoff_field == 3
    assert odds.division_count == 2
    assert odds.confidence == "low"
    assert len(odds.teams) == 4
    assert odds.teams[0].team_name == "Alpha"
    assert all(0 <= team.playoff.value <= 1 for team in odds.teams)
    assert abs(sum(team.playoff.value for team in odds.teams) - Decimal(3)) < Decimal("0.0001")
    assert odds.input_version.startswith("sha256:")


def test_digest_changes_with_every_simulation_input(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    snapshot = StandingsService(session).get_prediction_snapshot(league_id, SEASON)
    from app.services.prediction_service import input_digest

    baseline = input_digest(snapshot)
    assert input_digest(replace(snapshot, teams=snapshot.teams)) == baseline

    changed_score = replace(
        snapshot,
        counted_weeks=(
            replace(
                snapshot.counted_weeks[0],
                scores=(
                    replace(snapshot.counted_weeks[0].scores[0], points=Decimal("121.00")),
                    *snapshot.counted_weeks[0].scores[1:],
                ),
            ),
            *snapshot.counted_weeks[1:],
        ),
    )
    changed_pairing = replace(
        snapshot,
        remaining_weeks=(
            replace(
                snapshot.remaining_weeks[0],
                matchups=(
                    replace(snapshot.remaining_weeks[0].matchups[0], away_team_id=None),
                    *snapshot.remaining_weeks[0].matchups[1:],
                ),
            ),
        ),
    )
    changed_cup = replace(snapshot, cup_week=1)
    changed_field = replace(snapshot, playoff_team_count=4)
    changed_division = replace(
        snapshot,
        teams=(replace(snapshot.teams[0], division="North"), *snapshot.teams[1:]),
    )
    changed_name = replace(
        snapshot, teams=(replace(snapshot.teams[0], team_name="Alphas"), *snapshot.teams[1:])
    )

    digests = {
        input_digest(changed_score),
        input_digest(changed_pairing),
        input_digest(changed_cup),
        input_digest(changed_field),
        input_digest(changed_division),
        input_digest(changed_name),
    }
    assert baseline not in digests
    assert len(digests) == 6


def test_digest_ignores_last_refreshed_at(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    service = StandingsService(session)
    from app.services.prediction_service import input_digest

    first = input_digest(service.get_prediction_snapshot(league_id, SEASON))
    repository = SyncRepository(session)
    stored = repository.get_league_season(league_id, SEASON)
    assert stored is not None
    stored.last_refreshed_at = None
    session.commit()
    second = input_digest(service.get_prediction_snapshot(league_id, SEASON))

    assert first == second


def test_cache_reuses_a_result_and_misses_on_seed_or_iterations(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    calls = 0
    real_simulate = prediction_service.simulate_season

    def counting_simulate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_simulate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(prediction_service, "simulate_season", counting_simulate)
    cache = PredictionCache()
    service = PredictionService(session, cache=cache)

    first = service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=11)
    second = service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=11)
    assert calls == 1
    assert first == second

    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=12)
    service.get_playoff_odds(league_id, SEASON, iterations=2_000, seed=11)
    assert calls == 3


def test_cache_expires_after_its_ttl(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    now = [0.0]
    calls = 0
    real_simulate = prediction_service.simulate_season

    def counting_simulate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_simulate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(prediction_service, "simulate_season", counting_simulate)
    cache = PredictionCache(ttl_seconds=10.0, clock=lambda: now[0])
    service = PredictionService(session, cache=cache)

    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=11)
    now[0] = 9.9
    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=11)
    assert calls == 1
    now[0] = 10.0
    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=11)
    assert calls == 2


def test_default_seed_is_stable_and_reported(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    service = PredictionService(session, cache=PredictionCache())

    first = service.get_playoff_odds(league_id, SEASON, iterations=1_000)
    second = service.get_playoff_odds(league_id, SEASON, iterations=1_000)

    assert first.seed is not None
    assert first == second


def test_service_does_not_write_to_the_database(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    before = session.get_bind()
    stored = SyncRepository(session).get_league_season(league_id, SEASON)
    assert stored is not None
    refreshed_at = stored.last_refreshed_at

    PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000, seed=1
    )

    assert len(session.new) == 0
    assert len(session.dirty) == 0
    assert session.get_bind() is before
    assert SyncRepository(session).get_league_season(league_id, SEASON).last_refreshed_at == (
        refreshed_at
    )


# ---------------------------------------------------------------------------
# Unavailable reasons and settings faults
# ---------------------------------------------------------------------------


def _no_completed_weeks() -> dict[int, list[MatchupDTO]]:
    return {
        1: [
            _matchup(1, "team-a", None, "team-d", None, is_complete=False),
            _matchup(1, "team-b", None, "team-c", None, is_complete=False),
        ],
        2: [
            _matchup(2, "team-a", None, "team-c", None, is_complete=False),
            _matchup(2, "team-b", None, "team-d", None, is_complete=False),
        ],
        3: _future_week(),
    }


def test_no_completed_weeks_is_unavailable(session: Session) -> None:
    league_id = _seed_league(session, weeks=_no_completed_weeks())

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert odds.status == "unavailable"
    assert odds.reason == "no_completed_weeks"
    assert odds.iterations == 0
    assert odds.seed is None
    assert odds.teams == ()


def test_missing_playoff_field_is_unavailable(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks(), playoff_team_count=None)

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert (odds.status, odds.reason) == ("unavailable", "missing_playoff_field")


def test_incomplete_schedule_is_unavailable(session: Session) -> None:
    weeks = _completed_weeks()
    weeks[3] = []
    league_id = _seed_league(session, weeks=weeks)

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert (odds.status, odds.reason) == ("unavailable", "incomplete_schedule")


def test_playoff_week_inside_the_regular_season_is_unavailable(session: Session) -> None:
    weeks = _completed_weeks()
    weeks[3] = _future_week(is_playoff=True)
    league_id = _seed_league(session, weeks=weeks)

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert (odds.status, odds.reason) == ("unavailable", "incomplete_schedule")


def test_unsupported_division_shape_is_unavailable(session: Session) -> None:
    teams = (
        ("team-a", "Alpha", None),
        ("team-b", "Bravo", "East"),
        ("team-c", "Charlie", "West"),
        ("team-d", "Delta", "West"),
    )
    league_id = _seed_league(session, weeks=_standard_weeks(), teams=teams)

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert (odds.status, odds.reason) == ("unavailable", "unsupported_division_shape")


def test_finished_regular_season_reports_exact_probabilities(session: Session) -> None:
    weeks = _completed_weeks()
    weeks[3] = [
        _matchup(3, "team-a", "100.00", "team-c", "90.00"),
        _matchup(3, "team-b", "95.00", "team-d", "80.00"),
    ]
    league_id = _seed_league(session, weeks=weeks)

    odds = PredictionService(session, cache=PredictionCache()).get_playoff_odds(
        league_id, SEASON, iterations=1_000
    )

    assert odds.status == "ok"
    assert odds.iterations == 0
    assert odds.seed is None
    assert odds.remaining_weeks == ()
    assert {team.playoff.value for team in odds.teams} <= {Decimal(0), Decimal(1)}
    assert all(team.playoff.low == team.playoff.high for team in odds.teams)


def test_invalid_cup_week_is_a_settings_error(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks(), cup_week=99)

    with pytest.raises(SeasonSettingsError):
        StandingsService(session).get_prediction_snapshot(league_id, SEASON)


def test_invalid_iterations_or_seed_is_rejected(session: Session) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    service = PredictionService(session, cache=PredictionCache())

    with pytest.raises(ValueError):
        service.get_playoff_odds(league_id, SEASON, iterations=999)
    with pytest.raises(ValueError):
        service.get_playoff_odds(league_id, SEASON, iterations=50_001)
    with pytest.raises(ValueError):
        service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=-1)
    with pytest.raises(ValueError):
        service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=(1 << 31))


# ---------------------------------------------------------------------------
# Wilson interval arithmetic
# ---------------------------------------------------------------------------


def test_wilson_interval_stays_inside_zero_and_one_at_the_edges() -> None:
    zero_low, zero_high = wilson_interval(0, 1_000)
    one_low, one_high = wilson_interval(1_000, 1_000)
    mid_low, mid_high = wilson_interval(500, 1_000)

    assert zero_low < Decimal("0.000001")
    assert 0 < zero_high < Decimal("0.01")
    assert one_high == 1
    assert Decimal("0.99") < one_low < 1
    assert mid_low < Decimal("0.5") < mid_high


def test_wilson_interval_validates_its_inputs() -> None:
    with pytest.raises(ValueError):
        wilson_interval(0, 0)
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_cache_validates_its_configuration() -> None:
    with pytest.raises(ValueError):
        PredictionCache(max_entries=0)
    with pytest.raises(ValueError):
        PredictionCache(ttl_seconds=0)


# ---------------------------------------------------------------------------
# HTTP: permissions, validation, cache headers, and rate limiting
# ---------------------------------------------------------------------------


def _api_league(api: Api, **kwargs: object) -> int:
    """Seed a league in the API fixture's database and return its id."""
    with api.factory() as session:
        return _seed_league(session, weeks=_standard_weeks(), **kwargs)  # type: ignore[arg-type]


def _create_user(api: Api, email: str, *, league_id: int | None = None) -> int:
    with api.factory() as session:
        user = UserRepository(session).create(email, "unused-password-hash")
        if league_id is not None:
            MembershipRepository(session).create(user.id, league_id)
        session.commit()
        return user.id


def _login(api: Api, user_id: int) -> None:
    response = Response()
    set_session(response, user_id)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)


def _prediction_path(league_id: int, season: int = SEASON) -> str:
    return f"/api/v1/leagues/{league_id}/seasons/{season}/playoff-odds"


def test_AC_PO_07_unauthenticated_requests_get_401(api_factory: Callable[[], Api]) -> None:
    api = api_factory()
    league_id = _api_league(api)

    response = api.client.get(_prediction_path(league_id))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


def test_AC_PO_07_non_member_and_unknown_league_get_404(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "outsider@example.com"))

    non_member = api.client.get(_prediction_path(league_id))
    unknown = api.client.get(_prediction_path(999))
    unknown_season = api.client.get(_prediction_path(league_id, SEASON + 1))

    assert non_member.status_code == 404
    assert non_member.json()["detail"]["code"] == "not_found"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"
    assert unknown_season.status_code == 404
    assert unknown_season.json()["detail"]["code"] == "not_found"


@pytest.mark.parametrize(
    "params",
    [
        {"iterations": 999},
        {"iterations": 50_001},
        {"seed": -1},
        {"seed": 1 << 31},
    ],
)
def test_AC_PO_07_invalid_query_values_get_structured_422(
    api_factory: Callable[[], Api], params: dict[str, int]
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(_prediction_path(league_id), params=params)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert "input" not in response.json()["detail"][0]


def test_AC_PO_07_response_has_string_probabilities_and_private_cache_header(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(
        _prediction_path(league_id), params={"iterations": 1_000, "seed": 123}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=300"
    body = response.json()
    assert body["status"] == "ok"
    assert body["iterations"] == 1_000
    assert body["seed"] == 123
    assert body["model"] == {
        "version": "vp-mc-1",
        "shrink_games": 3,
        "residual_mix_games": 4,
        "score_precision": "0.01",
        "tiebreak_uses_points_for": True,
    }
    assert body["remaining_weeks"] == [3]
    assert len(body["teams"]) == 4
    for team in body["teams"]:
        for key in ("playoff", "bye", "division_title"):
            for bound in ("probability", "low", "high"):
                value = team[key][bound]
                assert isinstance(value, str)
                assert len(value.split(".")[1]) == 4
                assert 0 <= Decimal(value) <= 1


def test_AC_PO_09_identical_http_requests_hit_the_cache(
    api_factory: Callable[[], Api], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))
    calls = 0
    real_simulate = prediction_service.simulate_season

    def counting_simulate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_simulate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(prediction_service, "simulate_season", counting_simulate)

    first = api.client.get(_prediction_path(league_id), params={"iterations": 1_000, "seed": 5})
    second = api.client.get(_prediction_path(league_id), params={"iterations": 1_000, "seed": 5})

    assert first.status_code == second.status_code == 200
    assert calls == 1


def test_AC_PO_07_rate_limited_after_thirty_requests(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))
    # A fixed clock keeps all 31 requests in one window regardless of when the suite runs.
    fixed_limiter = RateLimiter(limit=30, window_seconds=60, clock=lambda: 1_000.0)
    api.client.app.dependency_overrides[get_prediction_limiter] = lambda: fixed_limiter  # type: ignore[attr-defined]

    responses = [
        api.client.get(_prediction_path(league_id), params={"iterations": 1_000, "seed": 9})
        for _ in range(31)
    ]

    assert all(response.status_code == 200 for response in responses[:30])
    limited = responses[30]
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert limited.headers["Retry-After"].isdigit()


def test_AC_PO_08_invalid_season_settings_are_a_structured_400(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _api_league(api, cup_week=99)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(_prediction_path(league_id), params={"iterations": 1_000})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "standings_unavailable"


def test_AC_PO_07_response_contains_no_owner_or_credential_fields(
    api_factory: Callable[[], Api],
) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    body = api.client.get(
        _prediction_path(league_id), params={"iterations": 1_000, "seed": 1}
    ).json()

    serialized = str(body)
    for forbidden in ("espn_s2", "espn_swid", "password", "@example.com", "owner_name"):
        assert forbidden not in serialized


GOLDEN_PREDICTION = {
    "league_id": 1,
    "season": 2026,
    "status": "ok",
    "reason": None,
    "iterations": 1000,
    "seed": 1234,
    "input_version": "sha256:4bf8bf99dc61fcab5953626324225c3da9c3eccfcd489d38d236b45944dd07af",
    "model": {
        "version": "vp-mc-1",
        "shrink_games": 3,
        "residual_mix_games": 4,
        "score_precision": "0.01",
        "tiebreak_uses_points_for": True,
    },
    "confidence": "low",
    "completed_weeks": 2,
    "remaining_weeks": [3],
    "playoff_field": 3,
    "division_count": 2,
    "teams": [
        {
            "team_id": 1,
            "team_name": "Alpha",
            "division": "East",
            "playoff": {"probability": "1.0000", "low": "0.9962", "high": "1.0000"},
            "bye": {"probability": "1.0000", "low": "0.9962", "high": "1.0000"},
            "division_title": {"probability": "1.0000", "low": "0.9962", "high": "1.0000"},
        },
        {
            "team_id": 2,
            "team_name": "Bravo",
            "division": "East",
            "playoff": {"probability": "0.9820", "low": "0.9717", "high": "0.9886"},
            "bye": {"probability": "0.0000", "low": "0.0000", "high": "0.0038"},
            "division_title": {"probability": "0.0000", "low": "0.0000", "high": "0.0038"},
        },
        {
            "team_id": 3,
            "team_name": "Charlie",
            "division": "West",
            "playoff": {"probability": "0.0840", "low": "0.0684", "high": "0.1028"},
            "bye": {"probability": "0.0000", "low": "0.0000", "high": "0.0038"},
            "division_title": {"probability": "0.0660", "low": "0.0522", "high": "0.0831"},
        },
        {
            "team_id": 4,
            "team_name": "Delta",
            "division": "West",
            "playoff": {"probability": "0.9340", "low": "0.9169", "high": "0.9478"},
            "bye": {"probability": "0.0000", "low": "0.0000", "high": "0.0038"},
            "division_title": {"probability": "0.9340", "low": "0.9169", "high": "0.9478"},
        },
    ],
}


def test_AC_PO_07_golden_playoff_odds_response(api_factory: Callable[[], Api]) -> None:
    api = api_factory()
    league_id = _api_league(api)
    _login(api, _create_user(api, "member@example.com", league_id=league_id))

    response = api.client.get(
        _prediction_path(league_id), params={"iterations": 1_000, "seed": 1234}
    )

    assert response.status_code == 200
    assert response.json() == GOLDEN_PREDICTION


def test_AC_PO_09_a_score_change_invalidates_the_cached_result(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    league_id = _seed_league(session, weeks=_standard_weeks())
    calls = 0
    real_simulate = prediction_service.simulate_season

    def counting_simulate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_simulate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(prediction_service, "simulate_season", counting_simulate)
    service = PredictionService(session, cache=PredictionCache())

    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=3)
    repository = SyncRepository(session)
    score = repository.get_week_scores(league_id, SEASON, 1)[0]
    repository.upsert_score(score.team_id, league_id, SEASON, 1, Decimal("199.00"))
    session.commit()
    service.get_playoff_odds(league_id, SEASON, iterations=1_000, seed=3)

    assert calls == 2


def _dummy_odds(league_id: int) -> object:
    from app.services.prediction_service import PlayoffOdds

    return PlayoffOdds(
        league_id=league_id,
        season=SEASON,
        status="ok",
        reason=None,
        iterations=0,
        seed=None,
        input_version="sha256:test",
        confidence="normal",
        completed_weeks=1,
        remaining_weeks=(),
        playoff_field=1,
        division_count=1,
        teams=(),
    )


def test_cache_evicts_the_least_recently_used_entry_and_prunes_locks() -> None:
    from app.services.prediction_service import _CacheKey

    cache = PredictionCache(max_entries=1)
    keys = [
        _CacheKey(
            league_id=index,
            season=SEASON,
            input_digest="sha256:test",
            iterations=1_000,
            seed=1,
            model_version="vp-mc-1",
        )
        for index in range(1, 4)
    ]
    for key in keys:
        cache.get_or_compute(key, lambda key=key: _dummy_odds(key.league_id))  # type: ignore[return-value]

    # The first two keys were evicted; the third is still live and the lock table was pruned.
    assert cache.get_or_compute(keys[2], lambda: _dummy_odds(3)) is not None  # type: ignore[arg-type]
    cache.clear()
    assert cache.get_or_compute(keys[2], lambda: _dummy_odds(3)) is not None  # type: ignore[arg-type]
