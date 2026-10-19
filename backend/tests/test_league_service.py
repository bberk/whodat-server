"""Service tests for league membership, credentials, owners, and refresh.

Every test is offline: provider construction is injected and backed by the in-memory
:class:`~app.providers.fake.FakeProvider`. Covers AC-AU-05/06/07/08/09/10/12/13 and AC-PR-01.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.auth_repositories import DuplicateMembershipError as DatabaseDuplicateMembershipError
from app.db.auth_repositories import MembershipRepository, UserRepository
from app.db.base import Base
from app.db.models import AppUser, League, LeagueSeason, Owner, Score, UserLeague
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
from app.providers.espn import credentials as espn_credentials
from app.providers.espn.credentials import create_espn_provider
from app.providers.fake import FakeProvider
from app.security.crypto import decrypt, encrypt
from app.services.league_service import (
    AlreadyMemberError,
    CredentialPermissionError,
    CredentialsRequiredError,
    EspnCredentials,
    IncompleteCredentialsError,
    InvalidLeagueRequestError,
    LeagueAccessError,
    LeagueNotFoundError,
    LeagueProviderError,
    LeagueService,
    LeagueSyncError,
    LeagueUser,
    NotAMemberError,
    OwnerNotFoundError,
    RefreshRateLimitedError,
    RefreshRateLimiter,
)
from app.services.sync_service import SyncError, SyncService

SEASON = 2026
LEAGUE_EXTERNAL = "espn-league-1"
S2 = "espn-s2-cookie-value"
SWID = "{SWID-COOKIE-VALUE}"
_KEY_A = bytes(range(32))
_KEY_B = bytes(range(32, 64))

type FakeSeed = tuple[
    LeagueDTO,
    list[OwnerDTO],
    list[TeamDTO],
    dict[int, list[MatchupDTO]],
    WeekStatus,
]


@pytest.fixture(autouse=True)
def _configured_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test a valid key and never leave a cached settings object behind."""
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY_A).decode("ascii"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """Provide a file-backed SQLite session so SAVEPOINT rollback is observable."""
    engine = create_engine(f"sqlite:///{tmp_path / 'league-service.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(
    *,
    external_id: str = LEAGUE_EXTERNAL,
    season: int = SEASON,
    last_completed_week: int | None = 1,
) -> dict[tuple[str, int], FakeSeed]:
    """Build a one-week, two-team league season for the fake provider."""
    metadata: dict[str, object] = {"regular_season_length": 1, "teams": 2}
    league = LeagueDTO(external_id=external_id, name="Test League", metadata=metadata)
    owners = [
        OwnerDTO(external_id="owner-1", display_name="Alice"),
        OwnerDTO(external_id="owner-2", display_name="Bob"),
    ]
    teams = [
        TeamDTO(
            external_id="team-1",
            name="Team A",
            division="East",
            owner_external_id="owner-1",
        ),
        TeamDTO(
            external_id="team-2",
            name="Team B",
            division="West",
            owner_external_id="owner-2",
        ),
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
            WeekStatus(last_completed_week=last_completed_week),
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


def _create_user(session: Session, email: str, role: str = "member") -> AppUser:
    user = UserRepository(session).create(email, "unused-password-hash", role=role)
    session.commit()
    return user


def _actor(user: AppUser) -> LeagueUser:
    return LeagueUser(user_id=user.id, role=user.role)


def _count(session: Session, model: type[Base]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _credentials() -> EspnCredentials:
    return EspnCredentials(espn_s2=S2, espn_swid=SWID)


def _seed_existing_league(
    session: Session,
    *,
    external_id: str = LEAGUE_EXTERNAL,
    provider_id: str = "fake",
    season: int = SEASON,
) -> League:
    repository = SyncRepository(session)
    league = repository.upsert_league(
        provider=provider_id,
        external_id=external_id,
        name="Stored League",
        league_metadata={"teams": 2},
        provider_config_ref="env:default",
    ).row
    repository.upsert_league_season(league.id, season, {"regular_season_length": 1})
    session.commit()
    return league


def _seed_membership(
    session: Session,
    *,
    user: AppUser,
    league: League,
    credentials: bool = True,
) -> UserLeague:
    memberships = MembershipRepository(session)
    membership = memberships.create(user.id, league.id)
    if credentials:
        memberships.set_credentials(
            user.id,
            league.id,
            espn_s2_encrypted=encrypt(S2),
            espn_swid_encrypted=encrypt(SWID),
        )
    session.commit()
    return membership


class FailAfterValidationProvider(FakeProvider):
    """Return league metadata but fail as soon as the sync asks for owners."""

    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]:
        raise RuntimeError("provider exploded with a sensitive url")


# ---------------------------------------------------------------------------
# AC-AU-06: admin credentialed add
# ---------------------------------------------------------------------------


def test_AC_AU_06_admin_add_with_credentials_encrypts_tokens_and_syncs(
    session: Session,
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    result = service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())
    service.commit()

    assert result.season == SEASON
    assert result.weeks_synced == (1,)
    assert result.membership.external_id == LEAGUE_EXTERNAL
    assert result.membership.name == "Test League"
    assert result.membership.has_credentials is True
    assert factory.decrypted == [(S2, SWID)]

    membership = session.scalar(select(UserLeague))
    assert membership is not None
    assert membership.espn_s2_encrypted is not None
    assert membership.espn_swid_encrypted is not None
    assert membership.espn_s2_encrypted != S2
    assert membership.espn_swid_encrypted != SWID
    assert decrypt(membership.espn_s2_encrypted) == S2
    assert decrypt(membership.espn_swid_encrypted) == SWID
    assert S2 not in repr(_credentials())
    assert SWID not in repr(_credentials())

    assert _count(session, League) == 1
    assert _count(session, UserLeague) == 1
    assert _count(session, LeagueSeason) == 1
    assert _count(session, Owner) == 2
    assert _count(session, Score) == 2


def test_AC_AU_06_admin_adds_new_public_league_without_credentials(
    session: Session,
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    result = service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON)
    service.commit()

    assert result.membership.external_id == LEAGUE_EXTERNAL
    assert result.membership.has_credentials is False
    assert result.weeks_synced == (1,)
    assert factory.public_calls == 1
    assert factory.calls == []

    membership = session.scalar(select(UserLeague))
    assert membership is not None
    assert membership.espn_s2_encrypted is None
    assert membership.espn_swid_encrypted is None
    assert _count(session, League) == 1
    assert _count(session, Owner) == 2
    assert _count(session, Score) == 2


def test_AC_AU_06_admin_no_credential_private_league_fails_without_writes(
    session: Session,
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    factory = RecordingFactory({})
    service = LeagueService(session, factory, provider_id="fake")

    with pytest.raises(LeagueAccessError) as error:
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON)

    assert "private leagues require ESPN credentials" in str(error.value)
    assert factory.public_calls == 1
    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0


def test_AC_AU_06_member_supplying_credentials_is_rejected_without_writes(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com", "member")
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    with pytest.raises(CredentialPermissionError):
        service.add_league(_actor(member), LEAGUE_EXTERNAL, SEASON, _credentials())

    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0
    assert factory.calls == []


def test_AC_AU_06_validation_failure_writes_nothing(session: Session) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    factory = RecordingFactory({})
    service = LeagueService(session, factory, provider_id="fake")

    with pytest.raises(LeagueProviderError):
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())

    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0


def test_AC_AU_06_initial_sync_failure_leaves_no_partial_rows(session: Session) -> None:
    admin = _create_user(session, "admin@example.com", "admin")

    class FailingFactory(RecordingFactory):
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

    service = LeagueService(session, FailingFactory(_seed()), provider_id="fake")

    with pytest.raises(LeagueSyncError) as error:
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())

    assert "sensitive url" not in str(error.value)
    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0
    assert _count(session, Owner) == 0
    assert _count(session, Score) == 0


def test_AC_AU_06_incomplete_credentials_are_rejected_before_any_write(
    session: Session,
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")

    with pytest.raises(IncompleteCredentialsError):
        service.add_league(
            _actor(admin),
            LEAGUE_EXTERNAL,
            SEASON,
            EspnCredentials(espn_s2=S2, espn_swid=""),
        )

    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0


# ---------------------------------------------------------------------------
# AC-AU-08: member joins an existing league
# ---------------------------------------------------------------------------


def test_AC_AU_08_member_joins_existing_league_without_credentials(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com", "member")
    _seed_existing_league(session)
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    result = service.add_league(_actor(member), LEAGUE_EXTERNAL)
    service.commit()

    assert result.membership.has_credentials is False
    assert result.weeks_synced == ()
    assert factory.calls == []
    membership = session.scalar(select(UserLeague))
    assert membership is not None
    assert membership.espn_s2_encrypted is None
    assert membership.espn_swid_encrypted is None


def test_AC_AU_08_member_join_missing_league_fails_without_writes(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com", "member")
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    with pytest.raises(LeagueNotFoundError):
        service.add_league(_actor(member), "not-stored")

    assert factory.public_calls == 0
    assert factory.calls == []
    session.commit()
    assert _count(session, UserLeague) == 0


# ---------------------------------------------------------------------------
# AC-AU-05: duplicate membership
# ---------------------------------------------------------------------------


def test_AC_AU_05_duplicate_membership_is_rejected(session: Session) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")
    service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())
    service.commit()
    calls_before = len(factory.calls)

    with pytest.raises(AlreadyMemberError):
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())

    assert len(factory.calls) == calls_before
    assert _count(session, UserLeague) == 1

    member = _create_user(session, "member@example.com", "member")
    service.add_league(_actor(member), LEAGUE_EXTERNAL)
    with pytest.raises(AlreadyMemberError):
        service.add_league(_actor(member), LEAGUE_EXTERNAL)
    assert _count(session, UserLeague) == 2


# ---------------------------------------------------------------------------
# Read scoping and owner association
# ---------------------------------------------------------------------------


def test_list_memberships_returns_only_the_callers_leagues(session: Session) -> None:
    first = _create_user(session, "first@example.com")
    second = _create_user(session, "second@example.com")
    first_league = _seed_existing_league(session, external_id="league-a")
    second_league = _seed_existing_league(session, external_id="league-b")
    _seed_membership(session, user=first, league=first_league)
    _seed_membership(session, user=second, league=second_league)
    service = LeagueService(session, RecordingFactory({}), provider_id="fake")

    views = service.list_memberships(_actor(first))

    assert [view.external_id for view in views] == ["league-a"]
    assert views[0].has_credentials is True


def test_AC_AU_10_list_seasons_and_owners_require_membership(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    outsider = _create_user(session, "outsider@example.com")
    league = _seed_existing_league(session)
    SyncRepository(session).upsert_owner(league.id, "owner-1", "Alice")
    SyncRepository(session).upsert_owner(league.id, "owner-2", "Bob")
    session.commit()
    _seed_membership(session, user=member, league=league)
    service = LeagueService(session, RecordingFactory({}), provider_id="fake")

    assert service.list_seasons(_actor(member), league.id) == [SEASON]
    owners = service.list_owners(_actor(member), league.id)
    assert [owner.display_name for owner in owners] == ["Alice", "Bob"]

    with pytest.raises(NotAMemberError):
        service.list_seasons(_actor(outsider), league.id)
    with pytest.raises(NotAMemberError):
        service.list_owners(_actor(outsider), league.id)


def test_AC_AU_12_set_owner_only_touches_the_callers_membership(session: Session) -> None:
    first = _create_user(session, "first@example.com")
    second = _create_user(session, "second@example.com")
    league = _seed_existing_league(session)
    other_league = _seed_existing_league(session, external_id="other-league")
    owners = SyncRepository(session)
    alice = owners.upsert_owner(league.id, "owner-1", "Alice").row
    owners.upsert_owner(league.id, "owner-2", "Bob")
    foreign = owners.upsert_owner(other_league.id, "owner-9", "Zoe").row
    session.commit()
    first_membership = _seed_membership(session, user=first, league=league, credentials=False)
    second_membership = _seed_membership(session, user=second, league=league, credentials=False)
    service = LeagueService(session, RecordingFactory({}), provider_id="fake")

    updated = service.set_owner(_actor(first), league.id, alice.id)
    service.commit()

    assert updated.owner_id == alice.id
    session.refresh(first_membership)
    session.refresh(second_membership)
    assert first_membership.owner_id == alice.id
    assert second_membership.owner_id is None

    cleared = service.set_owner(_actor(first), league.id, None)
    service.commit()
    assert cleared.owner_id is None

    with pytest.raises(OwnerNotFoundError):
        service.set_owner(_actor(first), league.id, foreign.id)

    outsider = _create_user(session, "outsider@example.com")
    with pytest.raises(NotAMemberError):
        service.set_owner(_actor(outsider), league.id, alice.id)


# ---------------------------------------------------------------------------
# AC-AU-09: refresh and rate limits
# ---------------------------------------------------------------------------


def test_AC_AU_09_refresh_uses_membership_credentials_and_current_season(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league)
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    result = service.refresh(_actor(member), league.id)
    service.commit()

    assert result.league_id == league.id
    assert result.season == SEASON
    assert result.weeks_synced == (1,)
    assert factory.decrypted == [(S2, SWID)]
    assert _count(session, Score) == 2


def test_AC_AU_09_refresh_without_credentials_is_rejected(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league, credentials=False)
    factory = RecordingFactory(_seed())
    service = LeagueService(session, factory, provider_id="fake")

    with pytest.raises(CredentialsRequiredError):
        service.refresh(_actor(member), league.id)

    assert factory.calls == []


def test_AC_AU_10_refresh_requires_membership(session: Session) -> None:
    outsider = _create_user(session, "outsider@example.com")
    league = _seed_existing_league(session)
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")

    with pytest.raises(NotAMemberError):
        service.refresh(_actor(outsider), league.id)


def test_AC_AU_09_refresh_is_limited_per_league(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league)
    now = [0.0]
    limiter = RefreshRateLimiter(clock=lambda: now[0])
    service = LeagueService(
        session, RecordingFactory(_seed()), provider_id="fake", refresh_limiter=limiter
    )

    service.refresh(_actor(member), league.id)
    with pytest.raises(RefreshRateLimitedError) as denied:
        service.refresh(_actor(member), league.id)

    assert denied.value.retry_after == 300

    now[0] = 299.0
    with pytest.raises(RefreshRateLimitedError) as almost:
        service.refresh(_actor(member), league.id)
    assert almost.value.retry_after == 1

    now[0] = 300.0
    service.refresh(_actor(member), league.id)
    service.commit()


def test_AC_AU_09_refresh_is_limited_per_user(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league)
    limiter = RefreshRateLimiter(league_interval_seconds=0.0, clock=lambda: 0.0)
    service = LeagueService(
        session, RecordingFactory(_seed()), provider_id="fake", refresh_limiter=limiter
    )

    for _ in range(3):
        service.refresh(_actor(member), league.id)

    with pytest.raises(RefreshRateLimitedError) as denied:
        service.refresh(_actor(member), league.id)

    assert denied.value.retry_after == 3600
    service.commit()


# ---------------------------------------------------------------------------
# AC-AU-07 / AC-AU-13: credential boundary and fail-closed encryption
# ---------------------------------------------------------------------------


def test_AC_AU_07_wrong_key_fails_closed_without_exposing_credentials(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league)
    ciphertext = session.scalar(select(UserLeague))
    assert ciphertext is not None
    stored_token = ciphertext.espn_s2_encrypted
    assert stored_token is not None

    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY_B).decode("ascii"))
    get_settings.cache_clear()
    service = LeagueService(session, create_espn_provider, provider_id="fake")

    try:
        with pytest.raises(LeagueProviderError) as error:
            service.refresh(_actor(member), league.id)
    finally:
        monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY_A).decode("ascii"))
        get_settings.cache_clear()

    message = str(error.value)
    assert S2 not in message
    assert SWID not in message
    assert stored_token not in message
    assert _count(session, Score) == 0


def test_invalid_league_input_is_rejected(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    service = LeagueService(session, RecordingFactory({}), provider_id="fake")

    with pytest.raises(InvalidLeagueRequestError):
        service.add_league(_actor(member), "   ")
    with pytest.raises(InvalidLeagueRequestError):
        service.add_league(_actor(member), LEAGUE_EXTERNAL, 0)


def test_refresh_falls_back_to_the_current_year_without_a_stored_season(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com")
    league = (
        SyncRepository(session)
        .upsert_league(
            provider="fake",
            external_id=LEAGUE_EXTERNAL,
            name="No Season Yet",
            league_metadata={},
            provider_config_ref="env:default",
        )
        .row
    )
    session.commit()
    _seed_membership(session, user=member, league=league)
    service = LeagueService(
        session,
        RecordingFactory(_seed(season=2030)),
        provider_id="fake",
        clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )

    result = service.refresh(_actor(member), league.id)

    assert result.season == 2030
    session.rollback()


def test_AC_AU_05_database_duplicate_race_is_reported_as_already_member(
    session: Session,
) -> None:
    member = _create_user(session, "member@example.com")
    _seed_existing_league(session)
    service = LeagueService(session, RecordingFactory({}), provider_id="fake")

    with (
        patch.object(
            MembershipRepository,
            "create",
            side_effect=DatabaseDuplicateMembershipError("concurrent duplicate"),
        ),
        pytest.raises(AlreadyMemberError),
    ):
        service.add_league(_actor(member), LEAGUE_EXTERNAL)

    session.rollback()
    assert _count(session, UserLeague) == 0


def test_AC_AU_07_encryption_key_failure_fails_closed(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")
    monkeypatch.delenv("LEAGUE_CREDENTIALS_KEY", raising=False)
    get_settings.cache_clear()

    try:
        with pytest.raises(LeagueProviderError) as error:
            service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())
    finally:
        monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY_A).decode("ascii"))
        get_settings.cache_clear()

    assert S2 not in str(error.value)
    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0


def test_AC_AU_06_sync_error_is_typed_and_writes_nothing(session: Session) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")

    with (
        patch.object(SyncService, "sync_league", side_effect=SyncError("provider failed")),
        pytest.raises(LeagueSyncError) as error,
    ):
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())

    assert "provider failed" not in str(error.value)
    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0


def test_refresh_sync_failure_rolls_back_the_savepoint(session: Session) -> None:
    member = _create_user(session, "member@example.com")
    league = _seed_existing_league(session)
    _seed_membership(session, user=member, league=league)
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")

    with (
        patch.object(SyncService, "sync_league", side_effect=RuntimeError("boom")),
        pytest.raises(LeagueSyncError),
    ):
        service.refresh(_actor(member), league.id)

    session.commit()
    assert _count(session, Score) == 0


def test_espn_provider_factory_decrypts_only_at_the_provider_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubProvider:
        provider_id = "espn"

        def __init__(
            self,
            *,
            league_factory: object = None,
            espn_s2: str | None = None,
            swid: str | None = None,
        ) -> None:
            captured["league_factory"] = league_factory
            captured["espn_s2"] = espn_s2
            captured["swid"] = swid

    monkeypatch.setattr(espn_credentials, "ESPNLeagueProvider", StubProvider)

    provider = create_espn_provider(
        espn_s2_encrypted=encrypt(S2),
        espn_swid_encrypted=encrypt(SWID),
    )

    assert isinstance(provider, StubProvider)
    assert captured == {"league_factory": None, "espn_s2": S2, "swid": SWID}


def test_espn_provider_factory_without_tokens_uses_explicit_empty_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubProvider:
        provider_id = "espn"

        def __init__(
            self,
            *,
            league_factory: object = None,
            espn_s2: str | None = None,
            swid: str | None = None,
        ) -> None:
            captured["league_factory"] = league_factory
            captured["espn_s2"] = espn_s2
            captured["swid"] = swid

    monkeypatch.setattr(espn_credentials, "ESPNLeagueProvider", StubProvider)

    provider = create_espn_provider()

    assert isinstance(provider, StubProvider)
    assert captured == {"league_factory": None, "espn_s2": "", "swid": ""}


def test_espn_provider_factory_rejects_half_a_credential_pair() -> None:
    with pytest.raises(ValueError, match="together"):
        create_espn_provider(espn_s2_encrypted=encrypt(S2))


def test_AC_AU_06_unexpected_write_failure_rolls_back_and_is_typed(
    session: Session,
) -> None:
    admin = _create_user(session, "admin@example.com", "admin")
    service = LeagueService(session, RecordingFactory(_seed()), provider_id="fake")

    with (
        patch.object(SyncRepository, "upsert_league", side_effect=RuntimeError("write failed")),
        pytest.raises(LeagueSyncError),
    ):
        service.add_league(_actor(admin), LEAGUE_EXTERNAL, SEASON, _credentials())

    session.commit()
    assert _count(session, League) == 0
    assert _count(session, UserLeague) == 0
