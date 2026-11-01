"""Active-week projection refresh, its schedule, and the projected read path.

Every fixture is written through the real sync service and the in-memory ``FakeProvider``. No
test calls ESPN or any other network service. The projection rows are seeded through
``FakeProvider.fetch_projections`` so the ingestion, storage, and read paths are exercised
together.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import AppUser, UserLeague
from app.db.repositories import SyncRepository
from app.projection_refresh import (
    build_trigger,
    refresh_active_weeks,
    start_projection_scheduler,
)
from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    ProjectionDTO,
    ProjectionSideDTO,
    ProviderAuthError,
    TeamDTO,
    WeekStatus,
)
from app.providers.fake import FakeProvider
from app.services.prediction_service import PredictionService
from app.services.standings_service import StandingsService
from app.services.sync_service import SyncService

SEASON = 2026
LEAGUE = "projection-league"
FIXED_NOW = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[tuple[sessionmaker[Session], Session]]:
    """Provide a session factory and one caller-owned session on an isolated SQLite database."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            yield factory, session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(
    *,
    week_2_complete: bool = False,
    length: int = 2,
    with_projections: bool = True,
) -> tuple[FakeProvider, dict[int, list[MatchupDTO]]]:
    """Build a 4-team seed with week 1 complete and week 2 as the active week.

    The projected week is deliberately hand-computable: week 2 projects 130/100 and 90/80, so
    the expected weekly VP is 3/1/1/-1 for teams 1/2/3/4.
    """
    league = LeagueDTO(
        external_id=LEAGUE,
        name="Projection League",
        metadata={"regular_season_length": length, "playoff_team_count": 4},
    )
    owners = [
        OwnerDTO(external_id=f"owner-{index}", display_name=f"Owner {index}")
        for index in range(1, 5)
    ]
    teams = [
        TeamDTO(
            external_id=f"team-{index}",
            name=f"Team {index}",
            division="East" if index <= 2 else "West",
            owner_external_id=f"owner-{index}",
        )
        for index in range(1, 5)
    ]
    matchups: dict[int, list[MatchupDTO]] = {
        1: [
            MatchupDTO(
                week=1,
                home=MatchupSideDTO("team-1", Decimal("120.00")),
                away=MatchupSideDTO("team-4", Decimal("90.00")),
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=1,
                home=MatchupSideDTO("team-2", Decimal("110.00")),
                away=MatchupSideDTO("team-3", Decimal("100.00")),
                is_playoff=False,
                is_complete=True,
            ),
        ],
        2: [
            MatchupDTO(
                week=2,
                home=MatchupSideDTO("team-1", Decimal("130.00") if week_2_complete else None),
                away=MatchupSideDTO("team-3", Decimal("100.00") if week_2_complete else None),
                is_playoff=False,
                is_complete=week_2_complete,
            ),
            MatchupDTO(
                week=2,
                home=MatchupSideDTO("team-2", Decimal("90.00") if week_2_complete else None),
                away=MatchupSideDTO("team-4", Decimal("80.00") if week_2_complete else None),
                is_playoff=False,
                is_complete=week_2_complete,
            ),
        ],
    }
    projections = {
        2: [
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-1", Decimal("130.00")),
                away=ProjectionSideDTO("team-3", Decimal("100.00")),
                is_playoff=False,
            ),
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-2", Decimal("90.00")),
                away=ProjectionSideDTO("team-4", Decimal("80.00")),
                is_playoff=False,
            ),
        ]
    }
    provider = FakeProvider(
        {(LEAGUE, SEASON): (league, owners, teams, matchups, WeekStatus(last_completed_week=1))},
        projections={((LEAGUE, SEASON)): projections} if with_projections else None,
    )
    return provider, matchups


def _sync(db: tuple[sessionmaker[Session], Session], provider: FakeProvider) -> int:
    factory, session = db
    summary = SyncService(provider, session, clock=lambda: FIXED_NOW).sync_league(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()
    return summary.league_id


def _add_credentials(session: Session, league_id: int, count: int = 1) -> None:
    for index in range(count):
        user = AppUser(
            email=f"credential-{index}@example.com",
            password_hash="hash",
            role="admin",
        )
        session.add(user)
        session.flush()
        session.add(
            UserLeague(
                user_id=user.id,
                league_id=league_id,
                espn_s2_encrypted=f"token-s2-{index}",
                espn_swid_encrypted=f"token-swid-{index}",
            )
        )
    session.commit()


def test_projection_trigger_fires_only_in_the_two_windows() -> None:
    """The combined trigger encodes Sunday 13:00-23:45 and Monday 20:00-23:45 exactly."""
    tz = ZoneInfo("America/New_York")
    trigger = build_trigger(tz)

    cases = [
        (datetime(2026, 11, 1, 12, 59, tzinfo=tz), "2026-11-01 13:00"),
        (datetime(2026, 11, 1, 23, 45, tzinfo=tz), "2026-11-01 23:45"),
        (datetime(2026, 11, 2, 0, 0, tzinfo=tz), "2026-11-02 20:00"),
        (datetime(2026, 11, 2, 23, 45, tzinfo=tz), "2026-11-02 23:45"),
    ]
    for now, expected in cases:
        fire = trigger.get_next_fire_time(None, now)
        assert fire is not None
        assert fire.strftime("%Y-%m-%d %H:%M") == expected


def test_projection_trigger_does_not_fire_on_other_days() -> None:
    """A Tuesday, Wednesday, and Saturday have no scheduled projection run."""
    tz = ZoneInfo("America/New_York")
    trigger = build_trigger(tz)
    fire = trigger.get_next_fire_time(None, datetime(2026, 11, 3, 12, 0, tzinfo=tz))
    assert fire is not None
    assert fire.strftime("%a %H:%M") == "Sun 13:00"


def test_scheduler_is_disabled_by_default() -> None:
    """No scheduler thread starts unless the production flag is on."""

    class Settings:
        projection_refresh_enabled = False

    assert start_projection_scheduler(Settings()) is None  # type: ignore[arg-type]


def test_active_week_stores_projections_and_records_as_of(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The refresh stores one projection per team and stamps the season's as-of instant."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    assert [(result.status, result.summary.active_week) for result in results] == [("ok", 2)]
    assert results[0].summary is not None
    assert results[0].summary.projections_stored == 4
    with db[0]() as check:
        rows = SyncRepository(check).get_week_projections(league_id, SEASON, 2)
        assert {row.team_id: row.points for row in rows} == {
            1: Decimal("130.00"),
            2: Decimal("90.00"),
            3: Decimal("100.00"),
            4: Decimal("80.00"),
        }
        season = SyncRepository(check).get_league_season(league_id, SEASON)
        assert season is not None
        assert season.projections_refreshed_at is not None


def test_active_week_rotates_credential_holders_on_auth_failure(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """An auth failure advances to the next member and still completes the refresh."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id, count=2)
    attempts: list[str] = []

    def factory(**kwargs: str | None):  # type: ignore[no-untyped-def]
        attempts.append(kwargs["espn_s2_encrypted"] or "")
        if len(attempts) == 1:
            raise ProviderAuthError("rejected")
        return provider

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=factory,
        clock=lambda: FIXED_NOW,
        random_source=random.Random(0),
    )

    assert results[0].status == "ok"
    assert len(attempts) == 2


def test_active_week_no_credentials_is_reported(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A league with no credential-holding membership reports no_credentials, not a crash."""
    provider, _ = _seed()
    _sync(db, provider)

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    assert [result.status for result in results] == ["no_credentials"]


def test_active_week_finalizes_a_completed_week_and_moves_on(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """When the active week becomes final, the refresh stores its VP and clears projections."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)

    final_provider, _ = _seed(week_2_complete=True)
    summary = SyncService(final_provider, session, clock=lambda: FIXED_NOW).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    assert summary.completed_week == 2
    assert summary.active_week is None
    assert summary.projections_stored == 0
    with db[0]() as check:
        assert SyncRepository(check).get_week_projections(league_id, SEASON, 2) == []
        standings = StandingsService(check).get_standings(league_id, SEASON)
        assert standings.completed_weeks == 2


def test_projected_standings_add_the_active_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """Projected VP, record, points for, ranks, and the week alignment are exact."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    actual = StandingsService(session).get_standings(league_id, SEASON)
    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    assert actual.weeks == (1,)
    assert projected.weeks == (1, 2)
    assert projected.completed_weeks == 1
    assert projected.active_week == 2
    assert projected.projection is not None
    assert projected.projection.week == 2
    assert projected.projection.reason is None

    by_team = {row.team_id: row for row in projected.overall}
    assert [row.team_id for row in projected.overall] == [1, 2, 3, 4]
    assert by_team[1].victory_points == 6
    assert by_team[2].victory_points == 3
    assert by_team[3].victory_points == 1
    assert by_team[4].victory_points == -2
    assert by_team[1].weekly_vp == (3, 3)
    assert by_team[2].weekly_vp == (2, 1)
    assert by_team[3].weekly_vp == (0, 1)
    assert by_team[4].weekly_vp == (-1, -1)
    assert (by_team[1].wins, by_team[1].losses) == (2, 0)
    assert (by_team[3].wins, by_team[3].losses) == (0, 2)
    assert by_team[1].points_for == Decimal("250.00")
    assert by_team[4].points_for == Decimal("170.00")
    assert by_team[1].rank == 1
    assert by_team[4].rank == 4


def test_projected_standings_are_unavailable_without_projections(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A missing projection does not partially fill the week; the reason is explicit."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)

    projected = StandingsService(db[1]).get_standings(league_id, SEASON, include_projected=True)

    assert projected.weeks == (1,)
    assert projected.active_week == 2
    assert projected.projection is not None
    assert projected.projection.week is None
    assert projected.projection.reason == "projections_not_synced"


def test_projected_vp_history_marks_the_projected_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The chart series gains one projected point and marks that week explicitly."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    history = StandingsService(session).get_vp_history(league_id, SEASON, include_projected=True)

    assert history.weeks == (1, 2)
    assert history.projected_weeks == (2,)
    team = next(entry for entry in history.teams if entry.team_id == 1)
    assert team.weekly == (3, 3)
    assert team.cumulative == (3, 6)


def test_projected_wapdate_includes_the_active_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The current period includes the projected week and its totals."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    wapdate = StandingsService(session).get_wapdate(league_id, SEASON, include_projected=True)

    assert wapdate.projected_week == 2
    assert len(wapdate.periods) == 1
    period = wapdate.periods[0]
    assert period.weeks == (1, 2)
    assert period.status == "current"
    assert period.rows[-1].team_id == 1
    assert period.rows[-1].vp == 6


def test_prediction_snapshot_fixes_only_the_active_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The snapshot keeps the strength weeks actual and moves the active week to fixed weeks."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    snapshot = StandingsService(session).get_prediction_snapshot(
        league_id, SEASON, include_projected=True
    )

    assert snapshot.projected_week == 2
    assert [week.week for week in snapshot.counted_weeks] == [1]
    assert snapshot.remaining_weeks == ()
    assert [week.week for week in snapshot.fixed_weeks] == [2]
    assert snapshot.projection is not None
    assert snapshot.projection.applied


def test_projected_odds_keep_the_strength_model_actual(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The projected run keeps actual counted weeks and removes the active week from remaining."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)

    service = PredictionService(session)
    actual = service.get_playoff_odds(league_id, SEASON, iterations=10, seed=7)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )
    projected = service.get_playoff_odds(
        league_id, SEASON, iterations=10, seed=7, include_projected=True
    )

    assert actual.status == "ok"
    assert projected.status == "ok"
    assert actual.completed_weeks == projected.completed_weeks == 1
    assert actual.remaining_weeks == (2,)
    assert projected.remaining_weeks == ()
    assert projected.projected_week == 2
    assert projected.projection_reason is None


def test_scheduler_starts_when_enabled_and_stops() -> None:
    """Enabling the flag starts one background scheduler that shuts down cleanly."""
    from types import SimpleNamespace

    settings = SimpleNamespace(
        projection_refresh_enabled=True,
        projection_refresh_timezone="America/New_York",
    )
    scheduler = start_projection_scheduler(settings)  # type: ignore[arg-type]
    assert scheduler is not None
    assert scheduler.running
    scheduler.shutdown(wait=False)


def test_scheduler_rejects_an_unknown_timezone() -> None:
    """A misconfigured timezone fails at startup instead of silently using UTC."""
    from types import SimpleNamespace

    settings = SimpleNamespace(
        projection_refresh_enabled=True,
        projection_refresh_timezone="Not/AZone",
    )
    with pytest.raises(RuntimeError):
        start_projection_scheduler(settings)  # type: ignore[arg-type]
