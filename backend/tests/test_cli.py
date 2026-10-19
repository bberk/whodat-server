"""CLI behavior tests for `app.cli`: sync, recompute, week parsing, and errors.

Every test injects a `FakeProvider`-backed `ProviderRegistry` and a session factory bound to an
isolated in-memory SQLite database, so nothing here touches ESPN, the live network, or the
configured development database (AC-DB-07).
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli import (
    DEFAULT_PROVIDER_ID,
    build_provider_registry,
    main,
    parse_week_range,
)
from app.db.base import Base
from app.db.models import League, Score
from app.db.repositories import SyncRepository
from app.providers.base import (
    LeagueDTO,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)
from app.providers.espn.settings import ESPNSettings
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry

LEAGUE_EXTERNAL_ID = "699385"
SEASON = 2026
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


def _registry(seed: dict[tuple[str, int], FakeSeed] | None = None) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeProvider(seed if seed is not None else _seed()))
    return registry


def _score_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Score)) or 0


def _vp_snapshot(session: Session) -> dict[tuple[int, int], Decimal]:
    return {
        (score.week, score.team_id): score.victory_points
        for score in session.scalars(select(Score)).all()
    }


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def test_cli_sync_writes_the_league_and_reports_a_summary(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A CLI sync persists rows and prints the weeks it synced and recomputed."""
    code = main(
        ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        registry=_registry(),
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "weeks_synced=1,2" in out
    assert "weeks_with_vp_recomputed=1,2" in out

    with session_factory() as session:
        league = session.scalar(select(League).where(League.provider == "fake"))
        assert league is not None
        assert league.provider_config_ref == "env:default"
        assert _score_count(session) == 4


def test_cli_sync_is_idempotent_when_repeated(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A second identical sync writes nothing new and reports no changes."""
    registry = _registry()
    argv = ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)]
    assert main(argv, registry=registry, session_factory=session_factory, provider_id="fake") == 0
    with session_factory() as session:
        counts_before = _score_count(session)
        vp_before = _vp_snapshot(session)

    capsys.readouterr()
    assert main(argv, registry=registry, session_factory=session_factory, provider_id="fake") == 0
    out = capsys.readouterr().out
    assert "league_changed=false" in out
    assert "weeks_with_vp_recomputed=-" in out

    with session_factory() as session:
        assert _score_count(session) == counts_before
        assert _vp_snapshot(session) == vp_before


def test_cli_sync_without_weeks_uses_completed_weeks(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """With no --weeks, only weeks up to the last completed week are stored."""
    seed = _seed(weeks=(1, 2, 3), last_completed_week=2, regular_season_length=3)
    code = main(
        ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        registry=_registry(seed),
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 0
    assert "weeks_synced=1,2" in capsys.readouterr().out
    with session_factory() as session:
        assert _score_count(session) == 4


def test_cli_sync_accepts_an_inclusive_week_range(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """--weeks 1-2 syncs weeks 1 through 2 inclusive even with no completed week reported."""
    seed = _seed(weeks=(1, 2, 3), last_completed_week=None, regular_season_length=3)
    code = main(
        ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON), "--weeks", "1-2"],
        registry=_registry(seed),
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 0
    assert "weeks_synced=1,2" in capsys.readouterr().out
    with session_factory() as session:
        assert _score_count(session) == 4


def test_cli_sync_supports_historical_seasons(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """The same league can be backfilled season by season with independent rows."""
    registry = _registry({**_seed(season=2025), **_seed(season=2026)})
    for season in (2025, 2026):
        code = main(
            ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(season)],
            registry=registry,
            session_factory=session_factory,
            provider_id="fake",
        )
        assert code == 0
        capsys.readouterr()

    with session_factory() as session:
        scores = session.scalars(select(Score)).all()
        # Two teams over two weeks in each of two seasons, stored independently.
        assert {score.season for score in scores} == {2025, 2026}
        assert len(scores) == 8


def test_cli_sync_unknown_league_reports_a_structured_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A league the provider does not know exits non-zero with a message, not a traceback."""
    code = main(
        ["sync", "--league", "does-not-exist", "--season", str(SEASON)],
        registry=_registry(),
        session_factory=session_factory,
        provider_id="fake",
    )

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "does-not-exist" in err


def test_cli_sync_unknown_provider_reports_a_structured_error(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """A provider id missing from the registry is reported instead of raising KeyError."""
    code = main(
        ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
        registry=_registry(),
        session_factory=session_factory,
        provider_id="sleeper",
    )

    assert code == 1
    assert "no provider registered" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# recompute
# ---------------------------------------------------------------------------


def test_cli_recompute_rebuilds_vp_from_stored_rows(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Recompute restores stored VP without any provider call and reports its weeks."""
    assert (
        main(
            ["sync", "--league", LEAGUE_EXTERNAL_ID, "--season", str(SEASON)],
            registry=_registry(),
            session_factory=session_factory,
            provider_id="fake",
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
            provider_config_ref="env:default",
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
    argv = [
        "sync",
        "--league",
        LEAGUE_EXTERNAL_ID,
        "--season",
        str(SEASON),
        "--weeks",
        value,
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv, registry=_registry(), session_factory=session_factory, provider_id="fake")

    assert excinfo.value.code == 2
    assert "--weeks" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# create-user stub
# ---------------------------------------------------------------------------


def test_cli_create_user_is_still_a_stub(capsys: pytest.CaptureFixture[str]) -> None:
    """create-user stays an explicit no-op until M4 implements auth."""
    assert main(["create-user"]) == 0
    assert "not implemented yet" in capsys.readouterr().out


def test_build_provider_registry_registers_espn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production wiring registers exactly the ESPN provider under its provider id."""
    monkeypatch.setattr(
        "app.providers.espn.adapter.get_espn_settings",
        lambda: ESPNSettings(_env_file=None, espn_s2="", espn_swid=""),
    )

    registry = build_provider_registry()

    assert DEFAULT_PROVIDER_ID == "espn"
    assert registry.get(DEFAULT_PROVIDER_ID).provider_id == "espn"
