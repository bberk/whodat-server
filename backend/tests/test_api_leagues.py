"""HTTP tests for the league routes, including the authorization matrix and secret hygiene.

The application is built with the same dependency overrides pattern as the auth API tests: a
temporary SQLite database, a fake-clock refresh limiter, and an injected provider factory backed by
:class:`~app.providers.fake.FakeProvider`. No test reaches ESPN.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import deps, routes_leagues
from app.api.main import create_app
from app.api.schemas_leagues import AddLeagueRequest
from app.api.session import SESSION_COOKIE_NAME, set_session
from app.config import get_settings
from app.db.auth_repositories import InviteRepository, MembershipRepository, UserRepository
from app.db.base import Base
from app.db.models import League, Owner, Team, UserLeague
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
from app.security.crypto import decrypt, encrypt
from app.security.invite_codes import hash_invite_code
from app.services.league_service import (
    AdminRequiredError,
    AlreadyMemberError,
    CredentialsRequiredError,
    DuplicateSeasonError,
    IncompleteCredentialsError,
    InvalidLeagueRequestError,
    InviteNotRedeemableError,
    LeagueAccessError,
    LeagueProviderError,
    LeagueService,
    LeagueServiceError,
    LeagueSyncError,
    NotAMemberError,
    OwnerNotFoundError,
    RefreshRateLimitedError,
    RefreshRateLimiter,
)
from app.services.sync_service import PROVIDER_CONFIG_REF

SEASON = 2026
LEAGUE_EXTERNAL = "espn-league-1"
S2 = "api-s2-cookie-value"
SWID = "{API-SWID-COOKIE-VALUE}"
_KEY = bytes(range(32))

type FakeSeed = tuple[
    LeagueDTO,
    list[OwnerDTO],
    list[TeamDTO],
    dict[int, list[MatchupDTO]],
    WeekStatus,
]


class FakeClock:
    """A deterministic seconds clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _configured_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure a valid credential key and clear cached settings before and after each test."""
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY).decode("ascii"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed(
    *,
    external_id: str = LEAGUE_EXTERNAL,
    season: int = SEASON,
) -> dict[tuple[str, int], FakeSeed]:
    """Build a one-week, two-team league season for the fake provider."""
    metadata: dict[str, object] = {"regular_season_length": 1, "teams": 2}
    league = LeagueDTO(external_id=external_id, name="API Test League", metadata=metadata)
    owners = [
        OwnerDTO(external_id="owner-1", display_name="Alice"),
        OwnerDTO(external_id="owner-2", display_name="Bob"),
    ]
    teams = [
        TeamDTO("team-1", "Team A", "East", "owner-1"),
        TeamDTO("team-2", "Team B", "West", "owner-2"),
    ]
    matchups = {
        1: [
            MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("90.00")),
                is_playoff=False,
                is_complete=True,
            )
        ]
    }
    return {
        (external_id, season): (
            league,
            owners,
            teams,
            matchups,
            WeekStatus(last_completed_week=1),
        )
    }


class RecordingFactory:
    """A provider factory that records the decrypted cookies it receives."""

    def __init__(self, seed: dict[tuple[str, int], FakeSeed]) -> None:
        self.seed = seed
        self.calls: list[tuple[str, str]] = []
        self.decrypted: list[tuple[str, str]] = []
        self.public_calls = 0

    def __call__(
        self,
        *,
        espn_s2_encrypted: str | None = None,
        espn_swid_encrypted: str | None = None,
    ) -> FakeProvider:
        if espn_s2_encrypted is None and espn_swid_encrypted is None:
            self.public_calls += 1
            return FakeProvider(self.seed)
        if espn_s2_encrypted is None or espn_swid_encrypted is None:
            raise ValueError("both credential tokens are required")
        self.calls.append((espn_s2_encrypted, espn_swid_encrypted))
        self.decrypted.append((decrypt(espn_s2_encrypted), decrypt(espn_swid_encrypted)))
        return FakeProvider(self.seed)


class FailAfterValidationProvider(FakeProvider):
    """Return league metadata but fail when sync asks for owners."""

    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]:
        raise RuntimeError("provider exploded with a sensitive url")


class FailingFactory(RecordingFactory):
    """Build a provider that validates but fails its first sync."""

    def __call__(
        self,
        *,
        espn_s2_encrypted: str | None = None,
        espn_swid_encrypted: str | None = None,
    ) -> FailAfterValidationProvider:
        if espn_s2_encrypted is not None and espn_swid_encrypted is not None:
            decrypt(espn_s2_encrypted)
            decrypt(espn_swid_encrypted)
        return FailAfterValidationProvider(self.seed)


@dataclass
class Api:
    """A test application plus the database, factory, and clock it uses."""

    client: TestClient
    engine: Engine
    factory: sessionmaker[Session]
    provider_factory: RecordingFactory
    clock: FakeClock
    limiter: RefreshRateLimiter


@pytest.fixture
def api_factory(tmp_path: Path) -> Iterator[Callable[..., Api]]:
    """Build isolated applications that share nothing but their route definitions."""
    engines: list[Engine] = []

    def build(
        *,
        seed: dict[tuple[str, int], FakeSeed] | None = None,
        provider_factory: RecordingFactory | None = None,
    ) -> Api:
        engine = create_engine(f"sqlite:///{tmp_path / f'leagues-{len(engines)}.db'}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        recording = provider_factory or RecordingFactory(seed if seed is not None else _seed())
        clock = FakeClock()
        limiter = RefreshRateLimiter(clock=clock)
        app = create_app()

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        def override_league_service() -> Iterator[LeagueService]:
            with factory() as session:
                yield LeagueService(
                    session,
                    recording,
                    provider_id="fake",
                    refresh_limiter=limiter,
                    clock=lambda: datetime(SEASON, 1, 1, tzinfo=UTC),
                )

        app.dependency_overrides[db_get_session] = override_session
        app.dependency_overrides[routes_leagues.get_league_service] = override_league_service
        return Api(
            client=TestClient(app),
            engine=engine,
            factory=factory,
            provider_factory=recording,
            clock=clock,
            limiter=limiter,
        )

    try:
        yield build
    finally:
        for engine in engines:
            Base.metadata.drop_all(engine)
            engine.dispose()


def _create_user(api: Api, email: str, role: str = "member") -> int:
    with api.factory() as session:
        user = UserRepository(session).create(email, "unused-password-hash", role=role)
        session.commit()
        return user.id


def _login(api: Api, user_id: int) -> None:
    response = Response()
    set_session(response, user_id)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)


def _seed_league(
    api: Api,
    *,
    external_id: str = LEAGUE_EXTERNAL,
    provider: str = "fake",
    season: int = SEASON,
    owners: int = 2,
    with_season: bool = True,
) -> int:
    with api.factory() as session:
        repository = SyncRepository(session)
        league = repository.upsert_league(
            provider=provider,
            external_id=external_id,
            name="Stored League",
            league_metadata={"teams": owners},
            provider_config_ref=PROVIDER_CONFIG_REF,
        ).row
        if with_season:
            repository.upsert_league_season(league.id, season, {"regular_season_length": 1})
        for index in range(1, owners + 1):
            repository.upsert_owner(league.id, f"owner-{index}", f"Owner {index}")
        session.commit()
        return league.id


def _seed_membership(
    api: Api,
    *,
    user_id: int,
    league_id: int,
    credentials: bool = False,
    owner_id: int | None = None,
) -> None:
    with api.factory() as session:
        memberships = MembershipRepository(session)
        memberships.create(user_id, league_id, owner_id=owner_id)
        if credentials:
            memberships.set_credentials(
                user_id,
                league_id,
                espn_s2_encrypted=encrypt(S2),
                espn_swid_encrypted=encrypt(SWID),
            )
        session.commit()


def _count(api: Api, model: type[Base]) -> int:
    with api.factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _seed_invite(
    api: Api,
    *,
    code: str = "member-invite-code",
    role: str = "member",
    league_id: int | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Store an invite for ``code`` and return the raw code."""
    with api.factory() as session:
        InviteRepository(session).create(
            league_id,
            hash_invite_code(code),
            expires_at or (datetime.now(UTC) + timedelta(days=7)),
            role=role,
        )
        session.commit()
    return code


def _add_payload(*, credentials: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "espn_league_id": LEAGUE_EXTERNAL,
        "season": SEASON,
    }
    if credentials:
        payload["espn_s2"] = S2
        payload["espn_swid"] = SWID
    return payload


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/v1/leagues", {"espn_league_id": LEAGUE_EXTERNAL}),
        ("post", "/api/v1/me/leagues/redeem-invite", {"invite_code": "code"}),
        ("get", "/api/v1/me/leagues", None),
        ("get", "/api/v1/leagues/1/seasons", None),
        ("post", "/api/v1/leagues/1/seasons", {"season": 2025}),
        ("get", "/api/v1/leagues/1/owners", None),
        ("put", "/api/v1/me/leagues/1/owner", {"owner_id": 1}),
        ("post", "/api/v1/leagues/1/refresh", None),
    ],
)
def test_AC_AU_10_unauthenticated_requests_return_401(
    api_factory: Callable[..., Api],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    api = api_factory()
    response = api.client.request(method, path, json=body)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


# ---------------------------------------------------------------------------
# Add and join
# ---------------------------------------------------------------------------


def test_AC_AU_06_admin_add_returns_201_and_never_echoes_credentials(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = api.client.post("/api/v1/leagues", json=_add_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["season"] == SEASON
    assert body["weeks_synced"] == [1]
    assert body["league"]["external_id"] == LEAGUE_EXTERNAL
    assert body["league"]["has_credentials"] is True
    assert api.provider_factory.decrypted == [(S2, SWID)]
    for secret in (S2, SWID, "espn_s2_encrypted", "espn_swid_encrypted"):
        assert secret not in response.text

    with api.factory() as session:
        membership = session.scalar(select(UserLeague))
        assert membership is not None
        assert membership.espn_s2_encrypted != S2
        assert membership.espn_swid_encrypted != SWID
        assert decrypt(membership.espn_s2_encrypted or "") == S2
        assert decrypt(membership.espn_swid_encrypted or "") == SWID


def test_AC_AU_06_admin_adds_new_public_league_without_credentials(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = api.client.post(
        "/api/v1/leagues", json={"espn_league_id": LEAGUE_EXTERNAL, "season": SEASON}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["league"]["has_credentials"] is False
    assert body["weeks_synced"] == [1]
    assert api.provider_factory.public_calls == 1
    assert api.provider_factory.calls == []

    with api.factory() as session:
        membership = session.scalar(select(UserLeague))
        assert membership is not None
        assert membership.espn_s2_encrypted is None
        assert membership.espn_swid_encrypted is None


def test_AC_AU_06_admin_no_credential_private_league_returns_400_and_stores_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = api.client.post(
        "/api/v1/leagues", json={"espn_league_id": LEAGUE_EXTERNAL, "season": SEASON}
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "league_unavailable"
    assert "private leagues require ESPN credentials" in detail["message"]
    assert api.provider_factory.public_calls == 1
    assert _count(api, League) == 0
    assert _count(api, UserLeague) == 0


def test_AC_AU_06_member_supplying_credentials_returns_403_and_stores_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    _login(api, member_id)

    response = api.client.post("/api/v1/leagues", json=_add_payload())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert api.provider_factory.calls == []
    assert _count(api, League) == 0
    assert _count(api, UserLeague) == 0


def test_AC_AU_08_member_add_by_id_returns_403_and_stores_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    _login(api, member_id)
    _seed_league(api)

    response = api.client.post("/api/v1/leagues", json={"espn_league_id": LEAGUE_EXTERNAL})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert api.provider_factory.calls == []
    assert api.provider_factory.public_calls == 0
    assert _count(api, UserLeague) == 0


def test_AC_AU_16_redeem_member_invite_returns_the_joined_league(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    code = _seed_invite(api, code="redeem-me", league_id=league_id)
    _login(api, member_id)

    response = api.client.post("/api/v1/me/leagues/redeem-invite", json={"invite_code": code})

    assert response.status_code == 201
    body = response.json()
    assert body["league"]["league_id"] == league_id
    assert body["league"]["external_id"] == LEAGUE_EXTERNAL
    assert body["league"]["has_credentials"] is False
    assert code not in response.text
    with api.factory() as session:
        membership = session.scalar(select(UserLeague))
        assert membership is not None
        assert membership.user_id == member_id
        assert membership.league_id == league_id
    assert _count(api, UserLeague) == 1


@pytest.mark.parametrize(
    ("role", "with_league", "expired"),
    [
        ("member", False, False),
        ("admin", True, False),
        ("member", True, True),
    ],
    ids=["member-without-league", "admin-role", "expired"],
)
def test_AC_AU_16_invalid_invites_return_400_and_store_nothing(
    api_factory: Callable[..., Api],
    role: str,
    with_league: bool,
    expired: bool,
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    code = _seed_invite(
        api,
        code="not-redeemable",
        role=role,
        league_id=league_id if with_league else None,
        expires_at=(datetime(2025, 12, 31, tzinfo=UTC)) if expired else None,
    )
    _login(api, member_id)

    response = api.client.post("/api/v1/me/leagues/redeem-invite", json={"invite_code": code})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_invite"
    assert code not in response.text
    assert _count(api, UserLeague) == 0


def test_AC_AU_16_unknown_invite_returns_400_and_stores_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    _seed_league(api)
    _login(api, member_id)

    response = api.client.post(
        "/api/v1/me/leagues/redeem-invite", json={"invite_code": "unknown-code"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_invite"
    assert "unknown-code" not in response.text
    assert _count(api, UserLeague) == 0


def test_AC_AU_05_redeem_duplicate_returns_409_and_keeps_one_membership(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    code = _seed_invite(api, code="duplicate-code", league_id=league_id)
    _login(api, member_id)

    first = api.client.post("/api/v1/me/leagues/redeem-invite", json={"invite_code": code})
    duplicate = api.client.post("/api/v1/me/leagues/redeem-invite", json={"invite_code": code})

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "already_member"
    assert code not in duplicate.text
    assert _count(api, UserLeague) == 1


def test_AC_AU_06_validation_failure_returns_structured_400_and_writes_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = api.client.post("/api/v1/leagues", json=_add_payload())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "league_unavailable"
    assert _count(api, League) == 0
    assert _count(api, UserLeague) == 0


def test_AC_AU_06_sync_failure_returns_structured_400_and_writes_nothing(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(provider_factory=FailingFactory(_seed()))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = api.client.post("/api/v1/leagues", json=_add_payload())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sync_failed"
    assert "sensitive url" not in response.text
    assert _count(api, League) == 0
    assert _count(api, UserLeague) == 0
    assert _count(api, Owner) == 0


def test_half_a_credential_pair_returns_422_without_echoing_it(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)
    secret = "only-s2-was-supplied"

    response = api.client.post(
        "/api/v1/leagues",
        json={"espn_league_id": LEAGUE_EXTERNAL, "espn_s2": secret},
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert all("input" not in error for error in response.json()["detail"])


# ---------------------------------------------------------------------------
# Membership-scoped reads
# ---------------------------------------------------------------------------


def test_AC_AU_10_seasons_and_owners_are_membership_scoped(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    seasons = api.client.get(f"/api/v1/leagues/{league_id}/seasons")
    owners = api.client.get(f"/api/v1/leagues/{league_id}/owners")

    assert seasons.status_code == 200
    assert seasons.json() == {"seasons": [SEASON]}
    assert owners.status_code == 200
    assert [owner["display_name"] for owner in owners.json()["owners"]] == [
        "Owner 1",
        "Owner 2",
    ]

    api.client.cookies.clear()
    _login(api, outsider_id)
    assert api.client.get(f"/api/v1/leagues/{league_id}/seasons").status_code == 404
    assert api.client.get(f"/api/v1/leagues/{league_id}/owners").status_code == 404


def test_me_leagues_returns_only_the_callers_memberships(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    other_id = _create_user(api, "other@example.com")
    first = _seed_league(api, external_id="league-a")
    second = _seed_league(api, external_id="league-b")
    _seed_membership(api, user_id=member_id, league_id=first)
    _seed_membership(api, user_id=other_id, league_id=second)
    _login(api, member_id)

    response = api.client.get("/api/v1/me/leagues")

    assert response.status_code == 200
    assert [league["external_id"] for league in response.json()] == ["league-a"]


# ---------------------------------------------------------------------------
# Owner association
# ---------------------------------------------------------------------------


def test_AC_AU_12_owner_update_only_changes_the_callers_membership(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    first_id = _create_user(api, "first@example.com")
    second_id = _create_user(api, "second@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=first_id, league_id=league_id)
    _seed_membership(api, user_id=second_id, league_id=league_id)
    with api.factory() as session:
        owner_ids = list(session.scalars(select(Owner.id).order_by(Owner.id)))
    _login(api, first_id)

    response = api.client.put(
        f"/api/v1/me/leagues/{league_id}/owner", json={"owner_id": owner_ids[0]}
    )

    assert response.status_code == 200
    assert response.json()["league"]["owner_id"] == owner_ids[0]
    with api.factory() as session:
        first = session.scalar(select(UserLeague).where(UserLeague.user_id == first_id))
        second = session.scalar(select(UserLeague).where(UserLeague.user_id == second_id))
        assert first is not None and first.owner_id == owner_ids[0]
        assert second is not None and second.owner_id is None

    cleared = api.client.put(f"/api/v1/me/leagues/{league_id}/owner", json={"owner_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["league"]["owner_id"] is None


def test_AC_AU_12_foreign_owner_and_non_member_are_rejected(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    other_league = _seed_league(api, external_id="other-league")
    with api.factory() as session:
        foreign_owner = (
            SyncRepository(session).upsert_owner(other_league, "owner-9", "Foreign").row.id
        )
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    foreign = api.client.put(
        f"/api/v1/me/leagues/{league_id}/owner", json={"owner_id": foreign_owner}
    )
    api.client.cookies.clear()
    _login(api, outsider_id)
    non_member = api.client.put(
        f"/api/v1/me/leagues/{league_id}/owner", json={"owner_id": foreign_owner}
    )

    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "not_found"
    assert non_member.status_code == 404


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


def test_AC_AU_09_refresh_returns_sync_summary(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id, credentials=True)
    _login(api, member_id)

    response = api.client.post(f"/api/v1/leagues/{league_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["league_id"] == league_id
    assert body["season"] == SEASON
    assert body["weeks_synced"] == [1]
    assert body["weeks_with_vp_recomputed"] == [1]
    assert api.provider_factory.decrypted == [(S2, SWID)]
    for secret in (S2, SWID):
        assert secret not in response.text


def test_AC_AU_09_refresh_without_credentials_returns_403(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    response = api.client.post(f"/api/v1/leagues/{league_id}/refresh")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "credentials_required"
    assert api.provider_factory.calls == []


def test_AC_AU_10_refresh_by_a_non_member_returns_404(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _login(api, outsider_id)

    response = api.client.post(f"/api/v1/leagues/{league_id}/refresh")

    assert response.status_code == 404


def test_AC_AU_09_refresh_returns_429_with_retry_after(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id, credentials=True)
    _login(api, member_id)

    first = api.client.post(f"/api/v1/leagues/{league_id}/refresh")
    second = api.client.post(f"/api/v1/leagues/{league_id}/refresh")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "300"
    assert second.json()["detail"]["code"] == "rate_limited"

    api.clock.advance(300)
    assert api.client.post(f"/api/v1/leagues/{league_id}/refresh").status_code == 200


# ---------------------------------------------------------------------------
# Add a season to an existing league
# ---------------------------------------------------------------------------


def _add_season(api: Api, league_id: int, season: int) -> httpx.Response:
    return api.client.post(f"/api/v1/leagues/{league_id}/seasons", json={"season": season})


def test_AC_AU_18_admin_adds_a_season_and_returns_the_weeks_synced(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed=_seed(season=2025))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    response = _add_season(api, league_id, 2025)

    assert response.status_code == 201
    body = response.json()
    assert body["league_id"] == league_id
    assert body["season"] == 2025
    assert body["weeks_synced"] == [1]
    assert api.provider_factory.decrypted == [(S2, SWID)]
    for secret in (S2, SWID, "espn_s2_encrypted", "espn_swid_encrypted"):
        assert secret not in response.text

    with api.factory() as session:
        seasons = [row.season for row in SyncRepository(session).list_league_seasons(league_id)]
        assert seasons == [2025, SEASON]


def test_AC_AU_18_duplicate_season_returns_409_and_skips_the_provider(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    response = _add_season(api, league_id, SEASON)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "season_exists"
    assert api.provider_factory.calls == []


def test_AC_AU_18_add_season_requires_an_admin(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id, credentials=True)
    _login(api, member_id)

    response = _add_season(api, league_id, 2025)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert api.provider_factory.calls == []


@pytest.mark.parametrize("role", ["admin", "member"])
def test_AC_AU_18_add_season_by_a_non_member_returns_404(
    api_factory: Callable[..., Api], role: str
) -> None:
    api = api_factory(seed=_seed(season=2025))
    user_id = _create_user(api, "outsider@example.com", role=role)
    league_id = _seed_league(api)
    _login(api, user_id)

    response = _add_season(api, league_id, 2025)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    assert api.provider_factory.calls == []


def test_AC_AU_18_add_season_for_an_unknown_league_returns_404(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed=_seed(season=2025))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    response = _add_season(api, 999, 2025)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_AC_AU_18_add_season_without_stored_credentials_returns_403(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed=_seed(season=2025))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = _add_season(api, league_id, 2025)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "credentials_required"
    assert api.provider_factory.calls == []


@pytest.mark.parametrize("season", [1999, 2101])
def test_AC_AU_18_invalid_season_year_returns_422_before_any_work(
    api_factory: Callable[..., Api], season: int
) -> None:
    api = api_factory(seed=_seed(season=2025))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    response = _add_season(api, league_id, season)

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    assert api.provider_factory.calls == []


def test_AC_AU_18_provider_failure_returns_400_and_leaves_no_season(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(provider_factory=FailingFactory(_seed(season=2025)))
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    response = _add_season(api, league_id, 2025)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sync_failed"
    assert "sensitive url" not in response.text
    with api.factory() as session:
        seasons = [row.season for row in SyncRepository(session).list_league_seasons(league_id)]
        assert seasons == [SEASON]
        teams = session.scalar(select(func.count()).select_from(Team).where(Team.season == 2025))
        assert teams == 0


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_responses_and_logs_never_contain_cookie_values_or_hashes(
    api_factory: Callable[..., Api],
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)
    caplog.set_level(logging.DEBUG)

    added = api.client.post("/api/v1/leagues", json=_add_payload())
    with api.factory() as session:
        membership = session.scalar(select(UserLeague))
        assert membership is not None
        stored_token = membership.espn_s2_encrypted or ""

    league_id = added.json()["league"]["league_id"]
    refreshed = api.client.post(f"/api/v1/leagues/{league_id}/refresh")
    listed = api.client.get("/api/v1/me/leagues")

    exposed = "\n".join([added.text, refreshed.text, listed.text, caplog.text])
    for secret in (S2, SWID, stored_token, "$argon2", "password_hash", "code_hash"):
        assert secret not in exposed


def test_default_dependencies_are_wired() -> None:
    """The production dependency builds a service and the auth limiter remains a singleton."""
    assert deps.get_rate_limiter() is deps.get_rate_limiter()


def test_refresh_sync_failure_returns_structured_400(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(provider_factory=FailingFactory(_seed()))
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id, credentials=True)
    _login(api, member_id)

    response = api.client.post(f"/api/v1/leagues/{league_id}/refresh")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sync_failed"


def test_production_league_service_dependency_builds(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    with api.factory() as session:
        service = routes_leagues.get_league_service(session)
    assert isinstance(service, LeagueService)


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (RefreshRateLimitedError(7), 429, "rate_limited"),
        (AdminRequiredError("x"), 403, "forbidden"),
        (InviteNotRedeemableError("x"), 400, "invalid_invite"),
        (CredentialsRequiredError("x"), 403, "credentials_required"),
        (NotAMemberError("x"), 404, "not_found"),
        (OwnerNotFoundError("x"), 404, "not_found"),
        (AlreadyMemberError("x"), 409, "already_member"),
        (DuplicateSeasonError("x"), 409, "season_exists"),
        (IncompleteCredentialsError("x"), 400, "invalid_credentials"),
        (InvalidLeagueRequestError("x"), 400, "invalid_request"),
        (LeagueAccessError("x"), 400, "league_unavailable"),
        (LeagueProviderError("x"), 400, "league_unavailable"),
        (LeagueSyncError("x"), 400, "sync_failed"),
        (LeagueServiceError("x"), 400, "request_failed"),
    ],
)
def test_service_errors_map_to_structured_http_responses(
    error: LeagueServiceError, status_code: int, code: str
) -> None:
    response: HTTPException = routes_leagues._http_error(error)

    assert response.status_code == status_code
    assert response.detail["code"] == code
    if isinstance(error, RefreshRateLimitedError):
        assert response.headers == {"Retry-After": "7"}


def test_add_league_schema_rejects_control_characters_and_whitespace() -> None:
    with pytest.raises(ValidationError):
        AddLeagueRequest(espn_league_id="bad\x00id")
    with pytest.raises(ValidationError):
        AddLeagueRequest(espn_league_id="bad id")
    with pytest.raises(ValidationError):
        AddLeagueRequest(
            espn_league_id=LEAGUE_EXTERNAL,
            espn_s2="bad\x00cookie",
            espn_swid=SWID,
        )
