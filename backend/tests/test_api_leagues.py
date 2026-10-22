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
from app.db.models import (
    AppUser,
    Invite,
    League,
    LeagueSeason,
    Matchup,
    Owner,
    Score,
    Team,
    UserLeague,
)
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
    InvalidCupWeekError,
    InvalidInviteRequestError,
    InvalidLeagueRequestError,
    InvalidSeasonSettingsError,
    InviteNotRedeemableError,
    LastAdminError,
    LeagueAccessError,
    LeagueMemberNotFoundError,
    LeagueProviderError,
    LeagueSeasonNotFoundError,
    LeagueService,
    LeagueServiceError,
    LeagueSyncError,
    NotAMemberError,
    OwnerNotFoundError,
    RefreshRateLimitedError,
    RefreshRateLimiter,
)
from app.services.sync_service import PROVIDER_CONFIG_REF, SyncService

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
        ("get", "/api/v1/leagues/1/seasons/settings", None),
        ("post", "/api/v1/leagues/1/seasons/2026/refresh", None),
        ("delete", "/api/v1/leagues/1/seasons/2026", None),
        ("get", "/api/v1/leagues/1/owners", None),
        ("put", "/api/v1/me/leagues/1/owner", {"owner_id": 1}),
        ("post", "/api/v1/leagues/1/refresh", None),
        ("get", "/api/v1/leagues/1/members", None),
        ("delete", "/api/v1/leagues/1/members/2", None),
        ("post", "/api/v1/leagues/1/invites", {"role": "member"}),
        ("delete", "/api/v1/leagues/1", None),
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

    settings = api.client.get(f"/api/v1/leagues/{league_id}/seasons/settings")
    assert settings.status_code == 200
    by_season = {row["season"]: row for row in settings.json()["seasons"]}
    assert by_season[2025]["last_refreshed_at"] is not None
    assert by_season[SEASON]["last_refreshed_at"] is None


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
        (InvalidCupWeekError("x"), 400, "invalid_cup_week"),
        (InvalidInviteRequestError("x"), 400, "invalid_invite"),
        (LastAdminError("x"), 409, "last_admin"),
        (InvalidSeasonSettingsError("x"), 400, "invalid_season_settings"),
        (InviteNotRedeemableError("x"), 400, "invalid_invite"),
        (CredentialsRequiredError("x"), 403, "credentials_required"),
        (NotAMemberError("x"), 404, "not_found"),
        (OwnerNotFoundError("x"), 404, "not_found"),
        (LeagueMemberNotFoundError("x"), 404, "not_found"),
        (LeagueSeasonNotFoundError("x"), 404, "not_found"),
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


# ---------------------------------------------------------------------------
# AC-API-07: cup-week read/update routes, authorization, validation, recompute
# ---------------------------------------------------------------------------


def _cup_week_path(league_id: int, season: int = SEASON) -> str:
    return f"/api/v1/leagues/{league_id}/seasons/{season}/cup-week"


def _seed_cup_week_league(api: Api, *, cup_week: int | None = None) -> int:
    """Sync a two-team, two-week league so cup-week scoring is observable in stored rows."""
    seed: dict[tuple[str, int], FakeSeed] = {
        (LEAGUE_EXTERNAL, SEASON): (
            LeagueDTO(
                external_id=LEAGUE_EXTERNAL,
                name="Cup Week League",
                metadata={"regular_season_length": 2, "teams": 2},
            ),
            [
                OwnerDTO(external_id="owner-1", display_name="Alice"),
                OwnerDTO(external_id="owner-2", display_name="Bob"),
            ],
            [
                TeamDTO("team-1", "Team A", "East", "owner-1"),
                TeamDTO("team-2", "Team B", "West", "owner-2"),
            ],
            {
                1: [
                    MatchupDTO(
                        week=1,
                        home=MatchupSideDTO(team_external_id="team-1", points=Decimal("100.00")),
                        away=MatchupSideDTO(team_external_id="team-2", points=Decimal("90.00")),
                        is_playoff=False,
                        is_complete=True,
                    )
                ],
                2: [
                    MatchupDTO(
                        week=2,
                        home=MatchupSideDTO(team_external_id="team-1", points=Decimal("95.00")),
                        away=MatchupSideDTO(team_external_id="team-2", points=Decimal("110.00")),
                        is_playoff=False,
                        is_complete=True,
                    )
                ],
            },
            WeekStatus(last_completed_week=2),
        )
    }
    with api.factory() as session:
        summary = SyncService(FakeProvider(seed), session).sync_league(
            LeagueRef(external_id=LEAGUE_EXTERNAL),
            "fake",
            SEASON,
        )
        if cup_week is not None:
            league_season = SyncRepository(session).get_league_season(summary.league_id, SEASON)
            assert league_season is not None
            league_season.cup_week = cup_week
        session.commit()
        return summary.league_id


def _stored_h2h(api: Api, league_id: int, week: int) -> dict[int, Decimal]:
    with api.factory() as session:
        return {
            score.team_id: score.vp_h2h
            for score in SyncRepository(session).get_week_scores(league_id, SEASON, week)
        }


def test_AC_API_07_get_cup_week_returns_null_by_default(api_factory: Callable[..., Api]) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    member_id = _create_user(api, "member@example.com")
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    response = api.client.get(_cup_week_path(league_id))

    assert response.status_code == 200
    assert response.json() == {
        "season": SEASON,
        "cup_week": None,
        "regular_season_length": 2,
    }


def test_AC_API_07_admin_setting_cup_week_recomputes_stored_scores(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)
    assert any(value != Decimal(0) for value in _stored_h2h(api, league_id, 2).values())

    response = api.client.put(_cup_week_path(league_id), json={"cup_week": 2})

    assert response.status_code == 200
    assert response.json() == {
        "season": SEASON,
        "cup_week": 2,
        "regular_season_length": 2,
    }
    assert all(value == Decimal(0) for value in _stored_h2h(api, league_id, 2).values())
    assert any(value != Decimal(0) for value in _stored_h2h(api, league_id, 1).values())
    # A cup-week change is provider-free: it recomputes only from stored data.
    assert api.provider_factory.calls == []
    assert api.provider_factory.public_calls == 0

    standings = api.client.get(f"/api/v1/leagues/{league_id}/seasons/{SEASON}/standings").json()
    rows = {row["team_name"]: row for row in standings["overall"]}
    assert (rows["Team A"]["wins"], rows["Team A"]["losses"]) == (1, 0)
    assert (rows["Team B"]["wins"], rows["Team B"]["losses"]) == (0, 1)
    assert rows["Team A"]["weekly_vp"] == ["3", "-1"]
    assert rows["Team B"]["weekly_vp"] == ["-1", "2"]
    assert rows["Team A"]["victory_points"] == "2"
    assert rows["Team B"]["victory_points"] == "1"
    assert rows["Team A"]["points_for"] == "195"
    assert rows["Team B"]["points_for"] == "200"


def test_AC_API_07_null_clears_the_cup_week_and_restores_wlt(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api, cup_week=2)
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.put(_cup_week_path(league_id), json={"cup_week": None})

    assert response.status_code == 200
    assert response.json()["cup_week"] is None
    # Week 2 is normal again: the winner gets +1 H2H and both weeks count for W/L.
    h2h = _stored_h2h(api, league_id, 2)
    assert sorted(h2h.values()) == [Decimal("0.000000"), Decimal("1.000000")]

    standings = api.client.get(f"/api/v1/leagues/{league_id}/seasons/{SEASON}/standings").json()
    rows = {row["team_name"]: row for row in standings["overall"]}
    assert (rows["Team A"]["wins"], rows["Team A"]["losses"]) == (1, 1)
    assert (rows["Team B"]["wins"], rows["Team B"]["losses"]) == (1, 1)


def test_AC_API_07_member_can_read_but_not_change_the_cup_week(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    member_id = _create_user(api, "member@example.com")
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    assert api.client.get(_cup_week_path(league_id)).status_code == 200
    response = api.client.put(_cup_week_path(league_id), json={"cup_week": 1})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    with api.factory() as session:
        stored = SyncRepository(session).get_league_season(league_id, SEASON)
        assert stored is not None
        assert stored.cup_week is None


def test_AC_API_07_non_member_and_unknown_season_return_404(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _login(api, admin_id)

    non_member_get = api.client.get(_cup_week_path(league_id))
    non_member_put = api.client.put(_cup_week_path(league_id), json={"cup_week": 1})
    unknown_league = api.client.get(_cup_week_path(999))
    unknown_season = api.client.get(_cup_week_path(league_id, season=2025))

    for response in (non_member_get, non_member_put, unknown_league, unknown_season):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"


def test_AC_API_07_member_unknown_season_and_unusable_settings_are_structured(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    member_id = _create_user(api, "member@example.com")
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    unknown_season = api.client.get(_cup_week_path(league_id, season=2025))
    assert unknown_season.status_code == 404
    assert unknown_season.json()["detail"]["code"] == "not_found"

    with api.factory() as session:
        league_season = SyncRepository(session).get_league_season(league_id, SEASON)
        assert league_season is not None
        league_season.league_season_metadata = {"teams": 2}
        session.commit()

    settings_error = api.client.get(_cup_week_path(league_id))
    assert settings_error.status_code == 400
    assert settings_error.json()["detail"]["code"] == "invalid_season_settings"


def test_AC_API_07_invalid_cup_week_values_are_rejected_without_a_write(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)
    admin_id = _create_user(api, "admin@example.com", role="admin")
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)
    scores_before = _stored_h2h(api, league_id, 2)

    for value in (0, -1, "one"):
        response = api.client.put(_cup_week_path(league_id), json={"cup_week": value})
        assert response.status_code == 422

    out_of_range = api.client.put(_cup_week_path(league_id), json={"cup_week": 3})
    assert out_of_range.status_code == 400
    assert out_of_range.json()["detail"]["code"] == "invalid_cup_week"

    missing = api.client.put(_cup_week_path(league_id), json={})
    assert missing.status_code == 422
    extra = api.client.put(_cup_week_path(league_id), json={"cup_week": 1, "other": True})
    assert extra.status_code == 422

    with api.factory() as session:
        stored = SyncRepository(session).get_league_season(league_id, SEASON)
        assert stored is not None
        assert stored.cup_week is None
    assert _stored_h2h(api, league_id, 2) == scores_before


def test_AC_API_07_unauthenticated_cup_week_requests_return_401(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(seed={})
    league_id = _seed_cup_week_league(api)

    get_response = api.client.get(_cup_week_path(league_id))
    put_response = api.client.put(_cup_week_path(league_id), json={"cup_week": 1})

    for response in (get_response, put_response):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "not_authenticated"


# ---------------------------------------------------------------------------
# AC-AU-23/24/25 and AC-API-09: season settings, per-season refresh, delete season
# ---------------------------------------------------------------------------


def _season_settings_path(league_id: int) -> str:
    return f"/api/v1/leagues/{league_id}/seasons/settings"


def _season_path(league_id: int, season: int = SEASON) -> str:
    return f"/api/v1/leagues/{league_id}/seasons/{season}"


def _refresh_season_path(league_id: int, season: int = SEASON) -> str:
    return f"{_season_path(league_id, season)}/refresh"


def _seed_two_synced_seasons(api: Api) -> int:
    """Sync 2025 and 2026 fixture seasons into one league through the sync service."""
    with api.factory() as session:
        seed = {**_seed(season=2025), **_seed(season=SEASON)}
        sync = SyncService(FakeProvider(seed), session)
        summary = sync.sync_league(LeagueRef(external_id=LEAGUE_EXTERNAL), "fake", 2025)
        sync.sync_league(LeagueRef(external_id=LEAGUE_EXTERNAL), "fake", SEASON)
        session.commit()
        return summary.league_id


def _season_row_counts(api: Api, league_id: int, season: int) -> dict[str, int]:
    with api.factory() as session:
        return {
            model.__tablename__: int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.league_id == league_id, model.season == season)
                )
                or 0
            )
            for model in (Team, Matchup, Score)
        }


def test_AC_AU_23_admin_lists_season_settings_with_nulls(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    with api.factory() as session:
        SyncRepository(session).upsert_league_season(league_id, 2025, {"regular_season_length": 14})
        session.commit()
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.get(_season_settings_path(league_id))

    assert response.status_code == 200
    assert response.json() == {
        "seasons": [
            {
                "season": 2025,
                "cup_week": None,
                "regular_season_length": 14,
                "last_refreshed_at": None,
            },
            {
                "season": SEASON,
                "cup_week": None,
                "regular_season_length": 1,
                "last_refreshed_at": None,
            },
        ]
    }
    assert api.provider_factory.calls == []
    assert api.provider_factory.public_calls == 0


def test_AC_AU_23_season_settings_requires_an_admin_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.get(_season_settings_path(league_id))
    api.client.cookies.clear()
    _login(api, admin_id)
    non_member = api.client.get(_season_settings_path(league_id))
    unknown = api.client.get(_season_settings_path(999))

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    for response in (non_member, unknown):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"


def test_AC_AU_24_admin_refreshes_one_season_and_records_the_timestamp(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    response = api.client.post(_refresh_season_path(league_id))

    assert response.status_code == 200
    assert response.json() == {"season": SEASON, "weeks_synced": [1]}
    assert api.provider_factory.decrypted == [(S2, SWID)]
    for secret in (S2, SWID):
        assert secret not in response.text
    # Refreshing a stored season neither creates a league nor duplicates the season.
    assert _count(api, League) == 1
    assert _count(api, LeagueSeason) == 1
    assert _count(api, Team) == 2

    settings = api.client.get(_season_settings_path(league_id)).json()["seasons"]
    refreshed_at = settings[0]["last_refreshed_at"]
    assert refreshed_at is not None
    assert datetime.fromisoformat(refreshed_at.replace("Z", "+00:00")) == datetime(
        SEASON, 1, 1, tzinfo=UTC
    )


def test_AC_AU_24_refresh_season_is_rate_limited(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)

    first = api.client.post(_refresh_season_path(league_id))
    second = api.client.post(_refresh_season_path(league_id))

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "300"
    assert second.json()["detail"]["code"] == "rate_limited"
    assert len(api.provider_factory.calls) == 1

    api.clock.advance(300)
    assert api.client.post(_refresh_season_path(league_id)).status_code == 200


def test_AC_AU_24_refresh_season_requires_admin_membership_and_a_stored_season(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    admin_id = _create_user(api, "admin@example.com", role="admin")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id, credentials=True)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.post(_refresh_season_path(league_id))
    api.client.cookies.clear()
    _login(api, outsider_id)
    non_member = api.client.post(_refresh_season_path(league_id))
    api.client.cookies.clear()
    _login(api, admin_id)
    no_credentials = api.client.post(_refresh_season_path(league_id))
    unknown_season = api.client.post(_refresh_season_path(league_id, 1999))

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    assert no_credentials.status_code == 403
    assert no_credentials.json()["detail"]["code"] == "credentials_required"
    for response in (non_member, unknown_season):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"
    assert api.provider_factory.calls == []


def test_AC_AU_25_delete_season_removes_only_that_seasons_data(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_two_synced_seasons(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _seed_invite(api, league_id=league_id)
    _login(api, admin_id)

    response = api.client.delete(_season_path(league_id, 2025))

    assert response.status_code == 204
    assert response.content == b""
    assert _count(api, League) == 1
    assert _count(api, Owner) == 2
    assert _count(api, UserLeague) == 2
    assert _count(api, Invite) == 1
    with api.factory() as session:
        seasons = [row.season for row in SyncRepository(session).list_league_seasons(league_id)]
    assert seasons == [SEASON]
    assert _season_row_counts(api, league_id, 2025) == {"team": 0, "matchup": 0, "score": 0}
    assert _season_row_counts(api, league_id, SEASON) == {
        "team": 2,
        "matchup": 1,
        "score": 2,
    }


def test_AC_AU_25_delete_season_requires_an_admin_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    admin_id = _create_user(api, "admin@example.com", role="admin")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_two_synced_seasons(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.delete(_season_path(league_id, 2025))
    api.client.cookies.clear()
    _login(api, outsider_id)
    non_member = api.client.delete(_season_path(league_id, 2025))
    api.client.cookies.clear()
    _login(api, admin_id)
    unknown = api.client.delete(_season_path(league_id, 1999))

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    for response in (non_member, unknown):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"
    assert _season_row_counts(api, league_id, 2025) == {
        "team": 2,
        "matchup": 1,
        "score": 2,
    }


# ---------------------------------------------------------------------------
# AC-AU-19/20/21/22: members, removal, invite generation, league deletion
# ---------------------------------------------------------------------------


def _league_members_path(league_id: int) -> str:
    return f"/api/v1/leagues/{league_id}/members"


def _league_invites_path(league_id: int) -> str:
    return f"/api/v1/leagues/{league_id}/invites"


def _owner_ids(api: Api, league_id: int) -> list[int]:
    with api.factory() as session:
        return list(
            session.scalars(select(Owner.id).where(Owner.league_id == league_id).order_by(Owner.id))
        )


def _seed_league_data(api: Api, *, league_id: int, season: int = SEASON) -> int:
    """Add one team, matchup, score, and league-bound invite so deletion has rows to remove."""
    with api.factory() as session:
        repository = SyncRepository(session)
        owner_id = session.scalar(
            select(Owner.id).where(Owner.league_id == league_id).order_by(Owner.id)
        )
        team = repository.upsert_team(league_id, season, "team-1", "Team A", "East", owner_id).row
        repository.upsert_matchup(league_id, season, 1, team.id, None, False, True)
        repository.upsert_score(team.id, league_id, season, 1, Decimal("100.00"))
        InviteRepository(session).create(
            league_id,
            hash_invite_code(f"bound-invite-{league_id}"),
            datetime.now(UTC) + timedelta(days=7),
            role="member",
        )
        session.commit()
        return team.id


def _count_where(api: Api, model: type[Base], condition: object) -> int:
    with api.factory() as session:
        return int(session.scalar(select(func.count()).select_from(model).where(condition)) or 0)


def test_AC_AU_19_admin_lists_members_with_email_role_owner_and_credentials(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    owner_id = _owner_ids(api, league_id)[0]
    _seed_membership(
        api, user_id=admin_id, league_id=league_id, credentials=True, owner_id=owner_id
    )
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.get(_league_members_path(league_id))

    assert response.status_code == 200
    members = response.json()["members"]
    assert [row["email"] for row in members] == ["admin@example.com", "member@example.com"]
    assert [row["role"] for row in members] == ["admin", "member"]
    assert members[0]["user_id"] == admin_id
    assert members[0]["owner_id"] == owner_id
    assert members[0]["owner_name"] == "Owner 1"
    assert members[0]["has_credentials"] is True
    assert members[1]["owner_id"] is None and members[1]["owner_name"] is None
    assert members[1]["has_credentials"] is False
    for secret in (S2, SWID, "unused-password-hash", "password_hash", "espn_s2_encrypted"):
        assert secret not in response.text


def test_AC_AU_19_members_list_requires_an_admin_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.get(_league_members_path(league_id))
    api.client.cookies.clear()
    _login(api, outsider_id)
    unknown = api.client.get(_league_members_path(league_id))

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"


def test_AC_AU_20_admin_removes_another_member_and_keeps_their_account_and_other_leagues(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    first = _seed_league(api, external_id="league-a")
    second = _seed_league(api, external_id="league-b")
    _seed_membership(api, user_id=admin_id, league_id=first)
    _seed_membership(api, user_id=member_id, league_id=first)
    _seed_membership(api, user_id=member_id, league_id=second)
    owners_before = _count_where(api, Owner, Owner.league_id == first)
    _login(api, admin_id)

    response = api.client.delete(f"{_league_members_path(first)}/{member_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert _count_where(api, UserLeague, UserLeague.league_id == first) == 1
    assert _count_where(api, UserLeague, UserLeague.league_id == second) == 1
    assert _count_where(api, AppUser, AppUser.id == member_id) == 1
    assert _count_where(api, Owner, Owner.league_id == first) == owners_before


def test_AC_AU_20_admin_may_remove_themselves_when_another_admin_remains(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    first_admin = _create_user(api, "first-admin@example.com", role="admin")
    second_admin = _create_user(api, "second-admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=first_admin, league_id=league_id)
    _seed_membership(api, user_id=second_admin, league_id=league_id)
    _login(api, first_admin)

    response = api.client.delete(f"{_league_members_path(league_id)}/{first_admin}")

    assert response.status_code == 204
    assert _count_where(api, UserLeague, UserLeague.league_id == league_id) == 1
    assert _count_where(api, AppUser, AppUser.id == first_admin) == 1


def test_AC_AU_20_removing_the_last_admin_member_is_blocked(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.delete(f"{_league_members_path(league_id)}/{admin_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "last_admin"
    assert _count_where(api, UserLeague, UserLeague.league_id == league_id) == 1


def test_AC_AU_20_removing_a_non_admin_member_is_allowed_next_to_one_admin(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.delete(f"{_league_members_path(league_id)}/{member_id}")

    assert response.status_code == 204
    assert _count_where(api, UserLeague, UserLeague.league_id == league_id) == 1


def test_AC_AU_20_removal_requires_admin_membership_and_an_existing_membership(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.delete(f"{_league_members_path(league_id)}/{admin_id}")
    api.client.cookies.clear()
    _login(api, outsider_id)
    non_member = api.client.delete(f"{_league_members_path(league_id)}/{member_id}")
    api.client.cookies.clear()
    _login(api, admin_id)
    unknown_member = api.client.delete(f"{_league_members_path(league_id)}/{outsider_id}")

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    assert non_member.status_code == 404
    assert non_member.json()["detail"]["code"] == "not_found"
    assert unknown_member.status_code == 404
    assert unknown_member.json()["detail"]["code"] == "not_found"


def test_AC_AU_21_member_invite_returns_the_code_once_and_stores_only_its_hash(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.post(_league_invites_path(league_id), json={"role": "member"})

    assert response.status_code == 201
    body = response.json()
    code = body["code"]
    assert code and len(code) >= 32
    assert body["role"] == "member"
    assert body["league_id"] == league_id
    assert body["expires_at"].startswith("2026-01-08")
    with api.factory() as session:
        invite = session.scalar(select(Invite))
        assert invite is not None
        assert invite.code_hash == hash_invite_code(code)
        assert code != invite.code_hash
        assert invite.league_id == league_id
        assert invite.role == "member"
        stored_hash = invite.code_hash
    listed = api.client.get(_league_members_path(league_id))
    assert code not in listed.text
    assert stored_hash not in listed.text


def test_AC_AU_21_admin_invite_is_league_less_and_defaults_to_seven_days(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.post(_league_invites_path(league_id), json={"role": "admin"})

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "admin"
    assert body["league_id"] is None
    assert body["expires_at"].startswith("2026-01-08")
    with api.factory() as session:
        invite = session.scalar(select(Invite))
        assert invite is not None
        assert invite.league_id is None
        assert invite.role == "admin"


@pytest.mark.parametrize("days", [1, 3650])
def test_AC_AU_21_invite_lifetime_accepts_the_bounds(
    api_factory: Callable[..., Api], days: int
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.post(
        _league_invites_path(league_id), json={"role": "member", "expires_in_days": days}
    )

    assert response.status_code == 201
    assert _count_where(api, Invite, Invite.league_id == league_id) == 1


@pytest.mark.parametrize("days", [0, -1, 3651])
def test_AC_AU_21_invite_lifetime_outside_the_bounds_returns_422(
    api_factory: Callable[..., Api], days: int
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.post(
        _league_invites_path(league_id), json={"role": "member", "expires_in_days": days}
    )

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    assert _count_where(api, Invite, Invite.league_id == league_id) == 0


def test_AC_AU_21_invite_creation_requires_an_admin_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.post(_league_invites_path(league_id), json={"role": "member"})
    api.client.cookies.clear()
    _login(api, outsider_id)
    unknown = api.client.post(_league_invites_path(league_id), json={"role": "admin"})

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"


def test_AC_AU_21_invite_role_must_be_admin_or_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.post(_league_invites_path(league_id), json={"role": "superuser"})

    assert response.status_code == 422
    assert _count_where(api, Invite, Invite.league_id == league_id) == 0


def test_AC_AU_22_delete_league_removes_only_that_leagues_data(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    member_id = _create_user(api, "member@example.com")
    doomed = _seed_league(api, external_id="doomed-league")
    survivor = _seed_league(api, external_id="survivor-league")
    _seed_league_data(api, league_id=doomed)
    _seed_league_data(api, league_id=survivor)
    _seed_membership(api, user_id=admin_id, league_id=doomed)
    _seed_membership(api, user_id=admin_id, league_id=survivor)
    _seed_membership(api, user_id=member_id, league_id=doomed)
    _seed_invite(api, code="league-less-admin", role="admin", league_id=None)
    _login(api, admin_id)

    response = api.client.delete(f"/api/v1/leagues/{doomed}")

    assert response.status_code == 204
    assert response.content == b""
    assert _count_where(api, League, League.id == doomed) == 0
    for model in (LeagueSeason, Owner, Team, Matchup, Score, UserLeague, Invite):
        assert _count_where(api, model, model.league_id == doomed) == 0
    # Only the other league and its rows survive, along with every account and admin invite.
    assert _count_where(api, League, League.id == survivor) == 1
    assert _count_where(api, LeagueSeason, LeagueSeason.league_id == survivor) == 1
    assert _count_where(api, Owner, Owner.league_id == survivor) == 2
    assert _count_where(api, Team, Team.league_id == survivor) == 1
    assert _count_where(api, Matchup, Matchup.league_id == survivor) == 1
    assert _count_where(api, Score, Score.league_id == survivor) == 1
    assert _count_where(api, UserLeague, UserLeague.league_id == survivor) == 1
    assert _count_where(api, Invite, Invite.league_id == survivor) == 1
    assert _count_where(api, AppUser, AppUser.id == admin_id) == 1
    assert _count_where(api, AppUser, AppUser.id == member_id) == 1
    assert _count_where(api, Invite, Invite.league_id.is_(None)) == 1


def test_AC_AU_22_delete_league_requires_an_admin_member(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    outsider_id = _create_user(api, "outsider@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    forbidden = api.client.delete(f"/api/v1/leagues/{league_id}")
    api.client.cookies.clear()
    _login(api, outsider_id)
    non_member = api.client.delete(f"/api/v1/leagues/{league_id}")
    unknown = api.client.delete("/api/v1/leagues/999")

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"
    assert non_member.status_code == 404
    assert non_member.json()["detail"]["code"] == "not_found"
    assert unknown.status_code == 404
    assert _count_where(api, League, League.id == league_id) == 1


# ---------------------------------------------------------------------------
# Input hardening: invite alphabet, path params, injection, request size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invite_code",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "with space",
        "with/slash",
        "with\x00nul",
        "with\u202ertl",
        "x" * 10_000,
    ],
)
def test_redeem_rejects_invite_codes_outside_the_generated_alphabet(
    api_factory: Callable[..., Api], invite_code: str
) -> None:
    """Redeem validates the token alphabet before any hash lookup or service call."""
    api = api_factory()
    member_id = _create_user(api, "member@example.com")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=member_id, league_id=league_id)
    _login(api, member_id)

    response = api.client.post(
        "/api/v1/me/leagues/redeem-invite", json={"invite_code": invite_code}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert invite_code not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert _count(api, UserLeague) == 1


@pytest.mark.parametrize(
    "suffix",
    [
        "leagues/0/seasons",
        "leagues/-1/seasons",
        "leagues/not-a-number/seasons",
        "leagues/{league_id}/seasons/0/cup-week",
        "leagues/{league_id}/seasons/1999/cup-week",
        "leagues/{league_id}/seasons/2101/cup-week",
        "leagues/{league_id}/seasons/not-a-number/cup-week",
    ],
)
def test_malformed_path_ids_and_seasons_return_422(
    api_factory: Callable[..., Api], suffix: str
) -> None:
    """A zero/negative id or unsupported season never reaches the service or a SQL predicate."""
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id)
    _login(api, admin_id)

    response = api.client.get("/api/v1/" + suffix.format(league_id=league_id))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert all("input" not in error for error in response.json()["detail"])


def test_sql_injection_and_markup_payloads_return_structured_4xx_without_query_errors(
    api_factory: Callable[..., Api],
) -> None:
    """Hostile values are rejected as data; no query error, traceback, or table loss leaks."""
    api = api_factory()
    admin_id = _create_user(api, "admin@example.com", role="admin")
    league_id = _seed_league(api)
    _seed_membership(api, user_id=admin_id, league_id=league_id, credentials=True)
    _login(api, admin_id)
    payloads = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
    ]
    requests: list[tuple[str, str, dict[str, object] | None]] = []
    for payload in payloads:
        requests.extend(
            [
                ("post", "/api/v1/leagues", {"espn_league_id": payload}),
                (
                    "post",
                    "/api/v1/me/leagues/redeem-invite",
                    {"invite_code": payload},
                ),
                (
                    "put",
                    f"/api/v1/me/leagues/{league_id}/owner",
                    {"owner_id": payload},
                ),
                (
                    "post",
                    f"/api/v1/leagues/{league_id}/seasons",
                    {"season": payload},
                ),
                (
                    "put",
                    f"/api/v1/leagues/{league_id}/seasons/{SEASON}/cup-week",
                    {"cup_week": payload},
                ),
            ]
        )
    requests.append(("get", "/api/v1/leagues/1%20OR%201=1/seasons", None))
    requests.append(
        ("get", f"/api/v1/leagues/{league_id}/seasons/%27%20OR%201%3D1%20--/cup-week", None)
    )

    for method, path, body in requests:
        response = api.client.request(method, path, json=body)
        assert 400 <= response.status_code < 500, (method, path, response.status_code)
        lowered = response.text.lower()
        for marker in ("operationalerror", "syntax error", "traceback", "sqlalchemy", "drop table"):
            assert marker not in lowered, (method, path, marker)

    # Legitimate reads still work, proving no request dropped or corrupted a table.
    assert api.client.get(f"/api/v1/leagues/{league_id}/seasons").status_code == 200
    assert _count(api, League) == 1
    assert _count(api, UserLeague) == 1


def test_oversized_request_body_returns_structured_413(
    api_factory: Callable[..., Api],
) -> None:
    """A body above the global cap is rejected before any schema or service code runs."""
    api = api_factory()
    oversized = b'{"email":"' + (b"x" * (64 * 1024)) + b'"}'

    response = api.client.post(
        "/api/v1/auth/signup",
        content=oversized,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "payload_too_large"
    assert "Traceback" not in response.text


def test_streamed_body_over_the_cap_returns_structured_413(
    api_factory: Callable[..., Api],
) -> None:
    """A chunked body with no Content-Length is capped while it is read."""

    def chunks() -> Iterator[bytes]:
        yield b"x" * 40_000
        yield b"x" * 40_000

    api = api_factory()
    response = api.client.post(
        "/api/v1/auth/login",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "payload_too_large"
