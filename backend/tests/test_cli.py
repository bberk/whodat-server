"""CLI behavior tests for `app.cli`: sync, recompute, week parsing, and errors.

Every sync test injects a credential-checking provider factory returning a `FakeProvider` and a
session factory bound to an isolated in-memory SQLite database, so nothing here touches ESPN, the
live network, or the configured development database (AC-DB-07). Stored cookies are real
ciphertext produced by the security layer under a test-only key (AC-AU-13).
"""

import base64
import inspect
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli import (
    DEFAULT_PROVIDER_ID,
    main,
    parse_week_range,
)
from app.config import get_settings
from app.db.auth_repositories import MembershipRepository, UserRepository
from app.db.base import Base
from app.db.models import ROLE_MEMBER, Invite, League, Score
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
from app.providers.espn.credentials import create_espn_provider
from app.providers.fake import FakeProvider
from app.security.crypto import CredentialDecryptionError, decrypt, encrypt
from app.security.invite_codes import hash_invite_code, invite_code_matches
from app.services.sync_service import PROVIDER_CONFIG_REF

LEAGUE_EXTERNAL_ID = "699385"
SEASON = 2026
MEMBER_EMAIL = "member@example.com"
SYNC_PROVIDER = "fake"
CREDENTIAL_S2 = "cli-s2-cookie"
CREDENTIAL_SWID = "{CLI-SWID}"
INVITE_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_KEY = bytes(range(32))
type FakeSeed = tuple[
    LeagueDTO,
    list[OwnerDTO],
    list[TeamDTO],
    dict[int, list[MatchupDTO]],
    WeekStatus,
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _configured_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test a valid credential key and never leave cached settings behind."""
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(_KEY).decode("ascii"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    """Provide a session factory over a fresh in-memory SQLite database.

    StaticPool keeps the same in-memory database alive across the several sessions the CLI opens.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(
    *,
    weeks: tuple[int, ...] = (1, 2),
    last_completed_week: int | None = 2,
    regular_season_length: int | None = 2,
    season: int = SEASON,
) -> dict[tuple[str, int], FakeSeed]:
    """Build a 2-team FakeProvider seed for the CLI league and season."""
    metadata: dict[str, object] = {"teams": 2}
    if regular_season_length is not None:
        metadata["regular_season_length"] = regular_season_length
    league = LeagueDTO(external_id=LEAGUE_EXTERNAL_ID, name="CLI League", metadata=metadata)
    owners = [
        OwnerDTO(external_id="owner-1", display_name="Alice"),
        OwnerDTO(external_id="owner-2", display_name="Bob"),
    ]
    teams = [
        TeamDTO(external_id="team-1", name="A Team", division="East", owner_external_id="owner-1"),
        TeamDTO(external_id="team-2", name="B Team", division="West", owner_external_id="owner-2"),
    ]
    matchups = {
        week: [
            MatchupDTO(
                week=week,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("120.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("100.00")),
                is_playoff=False,
                is_complete=True,
            )
        ]
        for week in weeks
    }
    return {
        (LEAGUE_EXTERNAL_ID, season): (
            league,
            owners,
            teams,
            matchups,
            WeekStatus(last_completed_week=last_completed_week),
        )
    }


class RecordingFactory:
    """A provider factory that records the decrypted cookies it is trusted with.

    It returns a ``FakeProvider`` so no network is involved. An optional error is raised instead,
    which lets a test exercise the CLI's credential-failure path.
    """

    def __init__(
        self,
        seed: dict[tuple[str, int], FakeSeed] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._provider = FakeProvider(seed if seed is not None else _seed())
        self._error = error
        self.calls: list[tuple[str, str]] = []
        self.decrypted: list[tuple[str, str]] = []

    def __call__(
        self,
        *,
        espn_s2_encrypted: str | None = None,
        espn_swid_encrypted: str | None = None,
    ) -> FakeProvider:
        if self._error is not None:
            raise self._error
        assert espn_s2_encrypted is not None
        assert espn_swid_encrypted is not None
        self.calls.append((espn_s2_encrypted, espn_swid_encrypted))
        self.decrypted.append((decrypt(espn_s2_encrypted), decrypt(espn_swid_encrypted)))
        return self._provider


def _sync_argv(
    *,
    email: str = MEMBER_EMAIL,
    season: int = SEASON,
    weeks: str | None = None,
) -> list[str]:
    """Build a sync invocation for the stored CLI league."""
    argv = [
        "sync",
        "--league",
        LEAGUE_EXTERNAL_ID,
        "--season",
        str(season),
        "--as-email",
        email,
    ]
    if weeks is not None:
        argv.extend(["--weeks", weeks])
    return argv


def _score_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Score)) or 0


def _vp_snapshot(session: Session) -> dict[tuple[int, int], Decimal]:
    return {
        (score.week, score.team_id): score.victory_points
        for score in session.scalars(select(Score)).all()
    }


def _fixed_clock() -> datetime:
    """Return the injected invite clock instant."""
    return INVITE_NOW


def _as_utc(value: datetime) -> datetime:
    """Treat a SQLite naive timestamp as UTC so expiry comparisons are deterministic."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _seed_league(
    session_factory: sessionmaker[Session],
    *,
    provider: str = DEFAULT_PROVIDER_ID,
    external_id: str = LEAGUE_EXTERNAL_ID,
) -> int:
    """Store the league row create-invite resolves by natural key and return its id."""
    with session_factory() as session:
        result = SyncRepository(session).upsert_league(
            provider=provider,
            external_id=external_id,
            name="CLI League",
            league_metadata={},
            provider_config_ref=PROVIDER_CONFIG_REF,
        )
        league_id = result.row.id
        session.commit()
    return league_id


def _create_user(
    session_factory: sessionmaker[Session],
    *,
    email: str = MEMBER_EMAIL,
    role: str = ROLE_MEMBER,
) -> int:
    """Store an account and return its id."""
    with session_factory() as session:
        user = UserRepository(session).create(email, "unused-password-hash", role=role)
        session.commit()
        return user.id


def _grant_membership(
    session_factory: sessionmaker[Session],
    *,
    user_id: int,
    league_id: int,
    credentials: bool = True,
) -> None:
    """Create a membership and optionally store encrypted ESPN cookies on it."""
    with session_factory() as session:
        memberships = MembershipRepository(session)
        memberships.create(user_id, league_id)
        if credentials:
            memberships.set_credentials(
                user_id,
                league_id,
                espn_s2_encrypted=encrypt(CREDENTIAL_S2),
                espn_swid_encrypted=encrypt(CREDENTIAL_SWID),
            )
        session.commit()


def _seed_sync_member(
    session_factory: sessionmaker[Session],
    *,
    email: str = MEMBER_EMAIL,
    credentials: bool = True,
    provider: str = SYNC_PROVIDER,
) -> None:
    """Store a league, an account, and a credentialed membership for CLI sync tests."""
    league_id = _seed_league(session_factory, provider=provider)
    user_id = _create_user(session_factory, email=email)
    _grant_membership(
        session_factory,
        user_id=user_id,
        league_id=league_id,
        credentials=credentials,
    )


def _invite_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Invite)) or 0


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def test_cli_sync_uses_the_members_stored_credentials_and_reports_a_summary(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-AU-13: sync builds its provider from the selected member's encrypted credentials."""
    _seed_sync_member(session_factory)
    factory = RecordingFactory()

    code = main(
        _sync_argv(),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "weeks_synced=1,2" in out
    assert "weeks_with_vp_recomputed=1,2" in out
    assert factory.decrypted == [(CREDENTIAL_S2, CREDENTIAL_SWID)]
    assert factory.calls[0][0] != CREDENTIAL_S2

    with session_factory() as session:
        league = session.scalar(select(League).where(League.provider == SYNC_PROVIDER))
        assert league is not None
        assert league.provider_config_ref == "membership"
        assert _score_count(session) == 4


def test_cli_sync_requires_as_email(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Sync without --as-email is a usage error and writes nothing."""
    _seed_sync_member(session_factory)

    with pytest.raises(SystemExit) as excinfo:
        main(
            ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )

    assert excinfo.value.code == 2
    assert "--as-email" in capsys.readouterr().err


def test_cli_sync_is_idempotent_when_repeated(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A second identical sync writes nothing new and reports no changes."""
    _seed_sync_member(session_factory)
    factory = RecordingFactory()
    argv = _sync_argv()
    assert (
        main(
            argv,
            provider_factory=factory,
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )
        == 0
    )
    with session_factory() as session:
        counts_before = _score_count(session)
        vp_before = _vp_snapshot(session)

    capsys.readouterr()
    assert (
        main(
            argv,
            provider_factory=factory,
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "league_changed=false" in out
    assert "weeks_with_vp_recomputed=-" in out

    with session_factory() as session:
        assert _score_count(session) == counts_before
        assert _vp_snapshot(session) == vp_before


def test_AC_DB_11_cli_sync_without_weeks_uses_full_regular_schedule(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """With no --weeks, a known season length syncs every scheduled regular-season week."""
    _seed_sync_member(session_factory)
    seed = _seed(weeks=(1, 2, 3), last_completed_week=2, regular_season_length=3)
    code = main(
        _sync_argv(),
        provider_factory=RecordingFactory(seed),
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "weeks_synced=1,2,3" in out
    assert "weeks_with_vp_recomputed=1,2,3" in out
    with session_factory() as session:
        assert _score_count(session) == 6


def test_cli_sync_accepts_an_inclusive_week_range(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """--weeks 1-2 syncs weeks 1 through 2 inclusive even with no completed week reported."""
    _seed_sync_member(session_factory)
    seed = _seed(weeks=(1, 2, 3), last_completed_week=None, regular_season_length=3)
    code = main(
        _sync_argv(weeks="1-2"),
        provider_factory=RecordingFactory(seed),
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 0
    assert "weeks_synced=1,2" in capsys.readouterr().out
    with session_factory() as session:
        assert _score_count(session) == 4


def test_cli_sync_supports_historical_seasons(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """The same league can be backfilled season by season with independent rows."""
    _seed_sync_member(session_factory)
    factory = RecordingFactory({**_seed(season=2025), **_seed(season=2026)})
    for season in (2025, 2026):
        code = main(
            _sync_argv(season=season),
            provider_factory=factory,
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )
        assert code == 0
        capsys.readouterr()

    with session_factory() as session:
        scores = session.scalars(select(Score)).all()
        # Two teams over two weeks in each of two seasons, stored independently.
        assert {score.season for score in scores} == {2025, 2026}
        assert len(scores) == 8


def test_cli_sync_unknown_user_exits_nonzero_without_syncing(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """An email with no account is a clear error and never calls the provider factory."""
    _seed_league(session_factory, provider=SYNC_PROVIDER)
    factory = RecordingFactory()

    code = main(
        _sync_argv(email="nobody@example.com"),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "user_not_found" in err
    assert factory.calls == []
    with session_factory() as session:
        assert _score_count(session) == 0


def test_cli_sync_blank_email_is_treated_as_an_unknown_user(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A blank --as-email is rejected as an unknown user rather than raising ValueError."""
    _seed_league(session_factory, provider=SYNC_PROVIDER)

    code = main(
        _sync_argv(email=""),
        provider_factory=RecordingFactory(),
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    assert "user_not_found" in capsys.readouterr().err


def test_cli_sync_unknown_league_exits_nonzero_without_syncing(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A league that is not stored cannot resolve a membership; nothing is written."""
    _create_user(session_factory)
    factory = RecordingFactory()

    code = main(
        _sync_argv(),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "league_not_found" in err
    assert factory.calls == []
    with session_factory() as session:
        assert _score_count(session) == 0


def test_cli_sync_non_member_exits_nonzero_without_syncing(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A known user without a membership in the league cannot sync it."""
    _seed_league(session_factory, provider=SYNC_PROVIDER)
    _create_user(session_factory)
    factory = RecordingFactory()

    code = main(
        _sync_argv(),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "not_a_member" in err
    assert factory.calls == []
    with session_factory() as session:
        assert _score_count(session) == 0


def test_cli_sync_membership_without_credentials_exits_nonzero(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A membership with no stored cookies is rejected before any provider is built."""
    _seed_sync_member(session_factory, credentials=False)
    factory = RecordingFactory()

    code = main(
        _sync_argv(),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "credentials_missing" in err
    assert factory.calls == []
    with session_factory() as session:
        assert _score_count(session) == 0


def test_cli_sync_never_falls_back_to_another_members_credentials(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the selected member's membership is consulted, even when another one has cookies."""
    _seed_sync_member(session_factory, email="with-creds@example.com")
    without = _create_user(session_factory, email="no-creds@example.com")
    league_id = _seed_league(session_factory, provider=SYNC_PROVIDER)
    _grant_membership(
        session_factory,
        user_id=without,
        league_id=league_id,
        credentials=False,
    )
    factory = RecordingFactory()

    code = main(
        _sync_argv(email="no-creds@example.com"),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    assert "credentials_missing" in capsys.readouterr().err
    assert factory.calls == []


def test_cli_sync_undecryptable_credentials_exit_cleanly_without_secrets(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A decryption failure is reported by code without echoing cookies or ciphertext."""
    _seed_sync_member(session_factory)
    factory = RecordingFactory(error=CredentialDecryptionError("token could not be decrypted"))

    code = main(
        _sync_argv(),
        provider_factory=factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "credentials_unavailable" in err
    assert CREDENTIAL_S2 not in err
    assert CREDENTIAL_SWID not in err
    assert "token could not be decrypted" not in err


def test_cli_sync_provider_unknown_league_reports_a_structured_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """The stored league missing from the provider is a sync failure, not a traceback."""
    _seed_sync_member(session_factory)

    code = main(
        _sync_argv(),
        provider_factory=RecordingFactory({}),
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error: sync_failed:")
    assert LEAGUE_EXTERNAL_ID in err


def test_cli_sync_provider_failure_hides_exception_details(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """An unexpected provider exception is replaced by a fixed message, not echoed."""

    class ExplodingProvider(FakeProvider):
        def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO:
            raise RuntimeError("raw provider text that must not be printed")

    def exploding_factory(
        *,
        espn_s2_encrypted: str | None = None,
        espn_swid_encrypted: str | None = None,
    ) -> FakeProvider:
        return ExplodingProvider({})

    _seed_sync_member(session_factory)

    code = main(
        _sync_argv(),
        provider_factory=exploding_factory,
        session_factory=session_factory,
        provider_id=SYNC_PROVIDER,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "sync_failed: league data could not be synced" in err
    assert "raw provider text" not in err


# ---------------------------------------------------------------------------
# recompute
# ---------------------------------------------------------------------------


def test_cli_recompute_rebuilds_vp_from_stored_rows(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Recompute restores stored VP without any provider call and reports its weeks."""
    _seed_sync_member(session_factory)
    assert (
        main(
            _sync_argv(),
            provider_factory=RecordingFactory(),
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )
        == 0
    )
    with session_factory() as session:
        expected = _vp_snapshot(session)
        for score in session.scalars(select(Score)).all():
            score.victory_points = Decimal("0")
        session.commit()

    capsys.readouterr()
    code = main(
        ["recompute", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "regular_season_length=2" in out
    assert "weeks_recomputed=1,2" in out
    with session_factory() as session:
        assert _vp_snapshot(session) == expected


def test_cli_recompute_missing_league_reports_a_structured_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Recomputing a league that was never synced exits non-zero with a clear message."""
    code = main(
        ["recompute", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "not stored" in err


def test_cli_recompute_season_without_a_league_season_row_exits_nonzero(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A stored league with no league_season row for the season is a structured exit-1 error."""
    # Store only the league row (as a schema change or manual insert could), no season row.
    with session_factory() as session:
        SyncRepository(session).upsert_league(
            provider="fake",
            external_id=LEAGUE_EXTERNAL_ID,
            name="CLI League",
            league_metadata={},
            provider_config_ref=PROVIDER_CONFIG_REF,
        )
        session.commit()

    code = main(
        ["recompute", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "league_season" in err
    assert str(SEASON) in err


# ---------------------------------------------------------------------------
# --weeks parsing and structured argparse errors
# ---------------------------------------------------------------------------


def test_parse_week_range_returns_inclusive_positive_weeks() -> None:
    """Single weeks and inclusive ranges both expand to ascending positive ints."""
    assert parse_week_range("3") == [3]
    assert parse_week_range("1-5") == [1, 2, 3, 4, 5]
    assert parse_week_range("2-2") == [2]
    assert parse_week_range(" 4-5 ") == [4, 5]
    # The supported ceiling is inclusive: week 30 is allowed, anything past it is rejected.
    assert parse_week_range("30") == [30]
    assert parse_week_range("29-30") == [29, 30]


@pytest.mark.parametrize(
    "value", ["0", "-1", "5-1", "1-", "1-2-3", "abc", "1.5", "", "1-0", "31", "1-31"]
)
def test_invalid_week_ranges_are_structured_argparse_errors(
    value: str, session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Bad --weeks values exit with argparse's usage error (code 2) and name the argument."""
    argv = _sync_argv(weeks=value)
    with pytest.raises(SystemExit) as excinfo:
        main(
            argv,
            provider_factory=RecordingFactory(),
            session_factory=session_factory,
            provider_id=SYNC_PROVIDER,
        )

    assert excinfo.value.code == 2
    assert "--weeks" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# create-invite
# ---------------------------------------------------------------------------


def test_cli_create_invite_stores_only_the_hash_and_prints_the_raw_code_once(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-AU-01: creation stores the hash plus role/expiry and prints the raw code exactly once.

    An admin invite has no league, so it is created before any league row exists.
    """
    code = main(
        ["create-invite", "--role", "admin"],
        session_factory=session_factory,
        clock=_fixed_clock,
    )

    assert code == 0
    captured = capsys.readouterr()
    raw_code = captured.out.rstrip("\n")
    assert captured.out == f"{raw_code}\n"
    assert captured.err == ""
    with session_factory() as session:
        invite = session.scalar(select(Invite))
        assert invite is not None
        assert invite.league_id is None
        assert invite.code_hash == hash_invite_code(raw_code)
        assert invite.role == "admin"
        assert _as_utc(invite.expires_at) == INVITE_NOW + timedelta(days=7)
        # The printed code is the only thing that can produce the stored digest.
        assert invite_code_matches(raw_code, invite.code_hash)


def test_cli_create_invite_member_without_a_league_is_a_usage_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A member invite must name a league; the missing flag exits 2 and writes nothing."""
    with pytest.raises(SystemExit) as excinfo:
        main(
            ["create-invite", "--role", "member"],
            session_factory=session_factory,
            clock=_fixed_clock,
        )

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--league" in err
    assert "member" in err
    with session_factory() as session:
        assert _invite_count(session) == 0


def test_cli_create_invite_admin_with_a_league_is_a_usage_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """An admin invite is league-less; supplying --league exits 2 and writes nothing."""
    with pytest.raises(SystemExit) as excinfo:
        main(
            ["create-invite", "--league", LEAGUE_EXTERNAL_ID, "--role", "admin"],
            session_factory=session_factory,
            clock=_fixed_clock,
        )

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--league" in err
    assert "admin" in err
    with session_factory() as session:
        assert _invite_count(session) == 0


@pytest.mark.parametrize(
    ("expires", "lifetime"),
    [
        ("7d", timedelta(days=7)),
        ("24h", timedelta(hours=24)),
        ("2", timedelta(days=2)),
        ("3650d", timedelta(days=3650)),
        ("87600h", timedelta(days=3650)),
    ],
)
def test_cli_create_invite_duration_accepts_days_hours_and_bare_integers(
    expires: str,
    lifetime: timedelta,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--expires accepts d and h suffixes and reads a bare integer as days."""
    _seed_league(session_factory)

    code = main(
        ["create-invite", "--league", LEAGUE_EXTERNAL_ID, "--role", "member", "--expires", expires],
        session_factory=session_factory,
        clock=_fixed_clock,
    )

    assert code == 0
    capsys.readouterr()
    with session_factory() as session:
        invite = session.scalar(select(Invite))
        assert invite is not None
        assert _as_utc(invite.expires_at) == INVITE_NOW + lifetime


def test_cli_create_invite_second_invite_creates_a_distinct_row_and_code(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Creating a second invite adds a new row with a different raw code and hash."""
    _seed_league(session_factory)

    printed_codes: list[str] = []
    for _ in range(2):
        assert (
            main(
                ["create-invite", "--league", LEAGUE_EXTERNAL_ID, "--role", "member"],
                session_factory=session_factory,
                clock=_fixed_clock,
            )
            == 0
        )
        printed_codes.append(capsys.readouterr().out.rstrip("\n"))

    assert printed_codes[0] != printed_codes[1]
    with session_factory() as session:
        invites = session.scalars(select(Invite).order_by(Invite.id)).all()
        assert len(invites) == 2
        assert len({invite.code_hash for invite in invites}) == 2
        assert [invite.role for invite in invites] == ["member", "member"]


def test_cli_create_invite_unknown_league_exits_nonzero_without_writing(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A league not stored for the provider is a clear error and leaves no invite row."""
    code = main(
        ["create-invite", "--league", "does-not-exist", "--role", "member"],
        session_factory=session_factory,
        clock=_fixed_clock,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "does-not-exist" in err
    with session_factory() as session:
        assert _invite_count(session) == 0


def test_cli_create_invite_unknown_provider_exits_nonzero_without_writing(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A provider with no stored league for this id is reported and writes nothing."""
    _seed_league(session_factory)

    code = main(
        [
            "create-invite",
            "--league",
            LEAGUE_EXTERNAL_ID,
            "--role",
            "member",
            "--provider",
            "sleeper",
        ],
        session_factory=session_factory,
        clock=_fixed_clock,
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "sleeper" in err
    with session_factory() as session:
        assert _invite_count(session) == 0


@pytest.mark.parametrize("role", ["owner", "", "Admin"])
def test_cli_create_invite_invalid_role_is_a_usage_error(
    role: str, session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Only admin and member are accepted; anything else exits 2 and writes nothing."""
    _seed_league(session_factory)

    with pytest.raises(SystemExit) as excinfo:
        main(
            ["create-invite", "--league", LEAGUE_EXTERNAL_ID, "--role", role],
            session_factory=session_factory,
            clock=_fixed_clock,
        )

    assert excinfo.value.code == 2
    assert "--role" in capsys.readouterr().err
    with session_factory() as session:
        assert _invite_count(session) == 0


@pytest.mark.parametrize("expires", ["0", "0d", "0h", "-1", "-1d", "abc", "1.5d", "1w", "", "d"])
def test_cli_create_invite_invalid_duration_is_a_usage_error(
    expires: str, session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero, negative, or malformed durations exit 2 without a traceback or an invite row."""
    _seed_league(session_factory)

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "create-invite",
                "--league",
                LEAGUE_EXTERNAL_ID,
                "--role",
                "member",
                "--expires",
                expires,
            ],
            session_factory=session_factory,
            clock=_fixed_clock,
        )

    assert excinfo.value.code == 2
    assert "--expires" in capsys.readouterr().err
    with session_factory() as session:
        assert _invite_count(session) == 0


@pytest.mark.parametrize(
    "expires", ["3651d", "87601h", "1000000000d", "1000000000h", "999999999999999999999d"]
)
def test_cli_create_invite_oversized_duration_is_a_usage_error(
    expires: str, session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A duration beyond 3650 days exits 2 with a usage message, never an OverflowError."""
    _seed_league(session_factory)

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "create-invite",
                "--league",
                LEAGUE_EXTERNAL_ID,
                "--role",
                "member",
                "--expires",
                expires,
            ],
            session_factory=session_factory,
            clock=_fixed_clock,
        )

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--expires" in err
    assert "3650" in err
    assert "Traceback" not in err
    assert "OverflowError" not in err
    with session_factory() as session:
        assert _invite_count(session) == 0


# ---------------------------------------------------------------------------
# Parser surface and module entry point
# ---------------------------------------------------------------------------


def test_cli_unknown_subcommand_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown subcommand (including the removed create-user) exits 2, not 0."""
    with pytest.raises(SystemExit) as excinfo:
        main(["create-user"])

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m app.cli --help` exits 0 through the module entry point."""
    monkeypatch.setattr("sys.argv", ["app.cli", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("app.cli", run_name="__main__")
    assert excinfo.value.code == 0
    assert "create-invite" in capsys.readouterr().out


def test_main_defaults_to_the_espn_credential_factory() -> None:
    """Production wiring builds sync providers through the decrypting ESPN factory."""
    default = inspect.signature(main).parameters["provider_factory"].default

    assert DEFAULT_PROVIDER_ID == "espn"
    assert default is create_espn_provider
