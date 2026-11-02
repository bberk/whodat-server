"""Active-week projection refresh, its schedule, and the projected read path.

Every fixture is written through the real sync service and the in-memory ``FakeProvider``. No
test calls ESPN or any other network service. The projection rows are seeded through
``FakeProvider.fetch_projections`` so the ingestion, storage, and read paths are exercised
together.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AppUser, UserLeague
from app.db.repositories import SyncRepository
from app.projection_refresh import (
    build_trigger,
    parse_league_ids,
    refresh_active_weeks,
    refresh_active_weeks_job,
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
    ProviderLeagueNotFound,
    TeamDTO,
    WeekStatus,
)
from app.providers.fake import FakeProvider
from app.security.crypto import CredentialDecryptionError
from app.services.prediction_service import PredictionService
from app.services.standings_service import StandingsService
from app.services.sync_service import (
    LeagueNotFoundError,
    MissingRegularSeasonLengthError,
    SyncError,
    SyncService,
)

SEASON = 2026
LEAGUE = "projection-league"
FIXED_NOW = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)


@pytest.fixture
def db(
    db_session_factory: sessionmaker[Session],
    db_session: Session,
) -> tuple[sessionmaker[Session], Session]:
    """Use the shared transaction-rollback database fixtures."""
    return db_session_factory, db_session


def _seed(
    *,
    week_2_complete: bool = False,
    length: int = 2,
    with_projections: bool = True,
    season: int = SEASON,
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
        {(LEAGUE, season): (league, owners, teams, matchups, WeekStatus(last_completed_week=1))},
        projections={((LEAGUE, season)): projections} if with_projections else None,
    )
    return provider, matchups


def _sync(db: tuple[sessionmaker[Session], Session], provider: FakeProvider) -> int:
    factory, session = db
    summary = SyncService(provider, session, clock=lambda: FIXED_NOW).sync_league(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()
    return summary.league_id


def _team_id_map(session: Session, league_id: int) -> dict[str, int]:
    """Resolve external team ids to database ids without assuming sequence values."""
    return {
        team.external_id: team.id for team in SyncRepository(session).get_teams(league_id, SEASON)
    }


def _metric(kind: str, outcome: str) -> float:
    """Read the current projection metric value for one outcome."""
    return (
        REGISTRY.get_sample_value("app_week_refresh_total", {"kind": kind, "outcome": outcome})
        or 0.0
    )


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
        team_ids = _team_id_map(check, league_id)
        rows = SyncRepository(check).get_week_projections(league_id, SEASON, 2)
        assert {row.team_id: row.points for row in rows} == {
            team_ids["team-1"]: Decimal("130.00"),
            team_ids["team-2"]: Decimal("90.00"),
            team_ids["team-3"]: Decimal("100.00"),
            team_ids["team-4"]: Decimal("80.00"),
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
    auth_before = _metric("projection", "auth_failed")
    ok_before = _metric("projection", "ok")

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
    assert _metric("projection", "auth_failed") == auth_before
    assert _metric("projection", "ok") == ok_before + 1


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

    team_ids = _team_id_map(session, league_id)
    by_team = {row.team_id: row for row in projected.overall}
    assert [row.team_id for row in projected.overall] == [
        team_ids["team-1"],
        team_ids["team-2"],
        team_ids["team-3"],
        team_ids["team-4"],
    ]
    assert by_team[team_ids["team-1"]].victory_points == 6
    assert by_team[team_ids["team-2"]].victory_points == 3
    assert by_team[team_ids["team-3"]].victory_points == 1
    assert by_team[team_ids["team-4"]].victory_points == -2
    assert by_team[team_ids["team-1"]].weekly_vp == (3, 3)
    assert by_team[team_ids["team-2"]].weekly_vp == (2, 1)
    assert by_team[team_ids["team-3"]].weekly_vp == (0, 1)
    assert by_team[team_ids["team-4"]].weekly_vp == (-1, -1)
    assert (by_team[team_ids["team-1"]].wins, by_team[team_ids["team-1"]].losses) == (2, 0)
    assert (by_team[team_ids["team-3"]].wins, by_team[team_ids["team-3"]].losses) == (0, 2)
    assert by_team[team_ids["team-1"]].points_for == Decimal("250.00")
    assert by_team[team_ids["team-4"]].points_for == Decimal("170.00")
    assert by_team[team_ids["team-1"]].rank == 1
    assert by_team[team_ids["team-4"]].rank == 4


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
    team_ids = _team_id_map(session, league_id)
    team = next(entry for entry in history.teams if entry.team_id == team_ids["team-1"])
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

    team_ids = _team_id_map(session, league_id)
    assert wapdate.projected_week == 2
    assert len(wapdate.periods) == 1
    period = wapdate.periods[0]
    assert period.weeks == (1, 2)
    assert period.status == "current"
    assert period.rows[-1].team_id == team_ids["team-1"]
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


def test_projected_view_refuses_a_schedule_gap(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A completed week after the active week is inconsistent, so the projection is not applied."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    with db[0]() as write:
        repository = SyncRepository(write)
        repository.upsert_league_season(
            league_id,
            SEASON,
            {"regular_season_length": 3, "playoff_team_count": 4},
        )
        teams = {team.external_id: team.id for team in repository.get_teams(league_id, SEASON)}
        for home, away in (("team-1", "team-2"), ("team-3", "team-4")):
            repository.upsert_matchup(
                league_id,
                SEASON,
                3,
                teams[home],
                teams[away],
                False,
                True,
            )
        for index, external_id in enumerate(("team-1", "team-2", "team-3", "team-4"), start=1):
            repository.upsert_score(
                teams[external_id],
                league_id,
                SEASON,
                3,
                Decimal(str(100 + index)),
            )
        write.commit()
    _add_credentials(session, league_id)
    refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    assert projected.projection is not None
    assert projected.projection.week is None
    assert projected.projection.reason == "incomplete_schedule"
    assert projected.weeks == (1, 3)


def test_no_active_week_when_the_season_is_complete(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A finished season clears projections and reports no active week."""
    provider, _ = _seed(week_2_complete=True)
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)

    summary = SyncService(provider, session, clock=lambda: FIXED_NOW).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    assert summary.active_week is None
    assert summary.completed_week is None
    assert summary.projections_stored == 0
    with db[0]() as check:
        assert SyncRepository(check).get_week_projections(league_id, SEASON, 2) == []


def test_incomplete_projection_clears_the_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """An empty projection response clears the active week instead of storing a guess."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)

    summary = SyncService(provider, session, clock=lambda: FIXED_NOW).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    assert summary.active_week == 2
    assert summary.projections_stored == 0
    with db[0]() as check:
        assert SyncRepository(check).get_week_projections(league_id, SEASON, 2) == []
    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)
    assert projected.projection is not None
    assert projected.projection.reason == "projections_not_synced"


def _valid_projection_list() -> list[ProjectionDTO]:
    return [
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


@pytest.mark.parametrize(
    "projections",
    [
        [],
        [
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-1", Decimal("130.00")),
                away=None,
                is_playoff=False,
            )
        ],
        [
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-1", None),
                away=ProjectionSideDTO("team-3", Decimal("100.00")),
                is_playoff=False,
            )
        ],
        [
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-1", Decimal("130.00")),
                away=ProjectionSideDTO("team-1", Decimal("100.00")),
                is_playoff=False,
            )
        ],
        _valid_projection_list()[:1],
        [
            *_valid_projection_list(),
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-9", Decimal("50.00")),
                away=None,
                is_playoff=False,
            ),
        ],
        [
            *_valid_projection_list()[:1],
            ProjectionDTO(
                week=2,
                home=ProjectionSideDTO("team-1", Decimal("50.00")),
                away=ProjectionSideDTO("team-3", Decimal("40.00")),
                is_playoff=True,
            ),
        ],
    ],
    ids=[
        "empty",
        "missing-side",
        "missing-points",
        "duplicate-team",
        "missing-matchup",
        "extra-team",
        "playoff-flag",
    ],
)
def test_invalid_projection_sets_clear_the_week(
    db: tuple[sessionmaker[Session], Session],
    projections: list[ProjectionDTO],
) -> None:
    """Every partial or malformed projection set leaves the active week unavailable."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    provider.set_projections(LeagueRef(external_id=LEAGUE), SEASON, {2: projections})

    summary = SyncService(provider, session, clock=lambda: FIXED_NOW).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    assert summary.active_week == 2
    assert summary.projections_stored == 0
    with db[0]() as check:
        assert SyncRepository(check).get_week_projections(league_id, SEASON, 2) == []
    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)
    assert projected.projection is not None
    assert projected.projection.reason in {
        "projections_not_synced",
        "projections_incomplete",
    }


def test_sync_active_week_reports_missing_league_settings_and_teams(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The unattended path rejects unknown leagues, missing settings, and empty rosters."""
    provider, _ = _seed()
    session = db[1]
    service = SyncService(provider, session, clock=lambda: FIXED_NOW)

    with pytest.raises(LeagueNotFoundError):
        service.sync_active_week(LeagueRef(external_id="unknown"), "fake", SEASON)

    league_id = _sync(db, provider)
    with pytest.raises(MissingRegularSeasonLengthError):
        service.sync_active_week(LeagueRef(external_id=LEAGUE), "fake", 2025)

    with db[0]() as write:
        repository = SyncRepository(write)
        empty_league = repository.upsert_league(
            "fake", "empty-settings", "Empty", {}, "membership"
        ).row
        repository.upsert_league_season(empty_league.id, SEASON, {})
        no_team_league = repository.upsert_league(
            "fake", "no-teams", "No Teams", {}, "membership"
        ).row
        repository.upsert_league_season(no_team_league.id, SEASON, {"regular_season_length": 2})
        write.commit()

    with pytest.raises(MissingRegularSeasonLengthError):
        service.sync_active_week(LeagueRef(external_id="empty-settings"), "fake", SEASON)
    with pytest.raises(SyncError):
        service.sync_active_week(LeagueRef(external_id="no-teams"), "fake", SEASON)
    assert league_id > 0


def test_empty_credentials_are_not_used(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A membership with blank tokens is not a credential holder."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    user = AppUser(email="blank@example.com", password_hash="hash", role="admin")
    session.add(user)
    session.flush()
    session.add(
        UserLeague(
            user_id=user.id,
            league_id=league_id,
            espn_s2_encrypted="",
            espn_swid_encrypted="",
        )
    )
    session.commit()

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=lambda **_: provider,
        clock=lambda: FIXED_NOW,
    )

    assert [result.status for result in results] == ["no_credentials"]


def test_credential_and_unexpected_errors_are_reported(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A key fault or an unexpected provider failure ends the league for this run."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _add_credentials(db[1], league_id)

    def crypto_failure(**_: str | None):  # type: ignore[no-untyped-def]
        raise CredentialDecryptionError("bad key")

    def unexpected_failure(**_: str | None):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    crypto_results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=crypto_failure,
        clock=lambda: FIXED_NOW,
    )
    assert [result.status for result in crypto_results] == ["failed"]
    unexpected_results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=unexpected_failure,
        clock=lambda: FIXED_NOW,
    )
    assert [result.status for result in unexpected_results] == ["failed"]


def test_all_rejected_credentials_report_auth_failure(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """Every holder being rejected is reported as auth_failed, not an exception."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _add_credentials(db[1], league_id, count=2)
    auth_before = _metric("projection", "auth_failed")

    def rejected(**_: str | None):  # type: ignore[no-untyped-def]
        raise ProviderAuthError("rejected")

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=rejected,
        clock=lambda: FIXED_NOW,
        random_source=random.Random(1),
    )

    assert [result.status for result in results] == ["auth_failed"]
    assert _metric("projection", "auth_failed") == auth_before + 1


def test_parse_league_ids_handles_empty_and_comma_lists() -> None:
    """An empty setting means every league; a comma list is trimmed and deduplicated by use."""
    assert parse_league_ids("") is None
    assert parse_league_ids("  ") is None
    assert parse_league_ids(" one, two , ") == ("one", "two")


def test_explicit_league_filter_skips_unknown_and_seasonless_leagues(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The configured list is exact; a league with no stored season contributes nothing."""
    provider, _ = _seed()
    _sync(db, provider)
    with db[0]() as write:
        SyncRepository(write).upsert_league("fake", "no-seasons", "Empty", {}, "membership")
        write.commit()

    assert (
        refresh_active_weeks(
            session_factory=db[0],
            provider_id="fake",
            provider_factory=lambda **_: provider,
            clock=lambda: FIXED_NOW,
            league_external_ids=("does-not-exist",),
        )
        == []
    )
    assert (
        refresh_active_weeks(
            session_factory=db[0],
            provider_id="fake",
            provider_factory=lambda **_: provider,
            clock=lambda: FIXED_NOW,
            league_external_ids=("no-seasons",),
        )
        == []
    )


def test_refresh_job_contains_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler entrypoint never lets an exception escape into the scheduler thread."""

    def explode(**_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.projection_refresh.refresh_active_weeks", explode)
    refresh_active_weeks_job()


def test_projection_reason_without_synced_projections(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The snapshot and odds report why a requested projection was not applied."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)
    _, session = db

    snapshot = StandingsService(session).get_prediction_snapshot(
        league_id, SEASON, include_projected=True
    )
    assert snapshot.projected_week is None
    assert snapshot.fixed_weeks == ()
    assert snapshot.projection is not None
    assert snapshot.projection.reason == "projections_not_synced"

    odds = PredictionService(session).get_playoff_odds(
        league_id, SEASON, iterations=10, seed=3, include_projected=True
    )
    assert odds.status == "ok"
    assert odds.projected_week is None
    assert odds.projection_reason == "projections_not_synced"


def test_sync_league_translates_a_provider_not_found(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A provider's typed not-found error becomes the sync service's LeagueNotFoundError."""
    provider, _ = _seed()

    class NotFound(FakeProvider):
        def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO:
            raise ProviderLeagueNotFound("missing")

    with pytest.raises(LeagueNotFoundError):
        SyncService(NotFound({}), db[1]).sync_league(
            LeagueRef(external_id="missing"), "fake", SEASON
        )


def test_partial_projection_rows_make_every_projected_read_unavailable(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """One missing team is a partial projection; every projected read reports it, never fills it."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)
    _, session = db
    with db[0]() as write:
        repository = SyncRepository(write)
        teams = {team.external_id: team.id for team in repository.get_teams(league_id, SEASON)}
        repository.upsert_projected_score(league_id, SEASON, 2, teams["team-1"], Decimal("130.00"))
        repository.set_league_season_projections_refreshed(league_id, SEASON, FIXED_NOW)
        write.commit()

    standings = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)
    history = StandingsService(session).get_vp_history(league_id, SEASON, include_projected=True)
    wapdate = StandingsService(session).get_wapdate(league_id, SEASON, include_projected=True)
    snapshot = StandingsService(session).get_prediction_snapshot(
        league_id, SEASON, include_projected=True
    )

    for projection in (
        standings.projection,
        history.projection,
        wapdate.projection,
        snapshot.projection,
    ):
        assert projection is not None
        assert projection.week is None
        assert projection.reason == "projections_incomplete"
    assert snapshot.fixed_weeks == ()
    assert wapdate.projected_week is None


def _store_projections(
    db: tuple[sessionmaker[Session], Session],
    league_id: int,
    week: int,
    points_by_external: dict[str, str],
) -> None:
    with db[0]() as write:
        repository = SyncRepository(write)
        teams = {team.external_id: team.id for team in repository.get_teams(league_id, SEASON)}
        for external_id, points in points_by_external.items():
            repository.upsert_projected_score(
                league_id, SEASON, week, teams[external_id], Decimal(points)
            )
        repository.set_league_season_projections_refreshed(league_id, SEASON, FIXED_NOW)
        write.commit()


def test_projected_read_without_an_active_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A complete season reports no_active_week for every projected read."""
    provider, _ = _seed(week_2_complete=True)
    league_id = _sync(db, provider)
    _, session = db

    for result in (
        StandingsService(session).get_standings(league_id, SEASON, include_projected=True),
        StandingsService(session).get_vp_history(league_id, SEASON, include_projected=True),
        StandingsService(session).get_wapdate(league_id, SEASON, include_projected=True),
    ):
        assert result.projection is not None
        assert result.projection.week is None
        assert result.projection.reason == "no_active_week"


def test_projected_cup_week_keeps_the_record_unchanged(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A projected cup week adds VP and points but no H2H win or loss."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    with db[0]() as write:
        season = SyncRepository(write).get_league_season(league_id, SEASON)
        assert season is not None
        season.cup_week = 2
        write.commit()
    _store_projections(
        db,
        league_id,
        2,
        {"team-1": "130", "team-2": "90", "team-3": "100", "team-4": "80"},
    )

    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    team_ids = _team_id_map(session, league_id)
    by_team = {row.team_id: row for row in projected.overall}
    assert by_team[team_ids["team-1"]].wins == 1
    assert by_team[team_ids["team-1"]].losses == 0
    assert by_team[team_ids["team-1"]].victory_points == 5


def test_projected_away_win_and_tie_updates_the_record(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The projected week's W-L-T record follows the away win and exact tie rules."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    _store_projections(
        db,
        league_id,
        2,
        {"team-1": "80", "team-2": "100", "team-3": "120", "team-4": "100"},
    )

    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    team_ids = _team_id_map(session, league_id)
    by_team = {row.team_id: row for row in projected.overall}
    assert (
        by_team[team_ids["team-1"]].wins,
        by_team[team_ids["team-1"]].losses,
    ) == (1, 1)
    assert (
        by_team[team_ids["team-3"]].wins,
        by_team[team_ids["team-3"]].losses,
    ) == (1, 1)
    assert by_team[team_ids["team-2"]].ties == 1
    assert by_team[team_ids["team-4"]].ties == 1


def test_projected_bye_has_no_head_to_head_record(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """An explicit bye in the projected week still earns VP and points but no H2H result."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    with db[0]() as write:
        repository = SyncRepository(write)
        teams = {team.external_id: team.id for team in repository.get_teams(league_id, SEASON)}
        for matchup in repository.get_week_matchups(league_id, SEASON, 2):
            repository.delete_matchup(matchup)
        repository.upsert_matchup(league_id, SEASON, 2, teams["team-1"], None, False, False)
        repository.upsert_matchup(
            league_id, SEASON, 2, teams["team-2"], teams["team-3"], False, False
        )
        repository.upsert_matchup(league_id, SEASON, 2, teams["team-4"], None, False, False)
        write.commit()
    _store_projections(
        db,
        league_id,
        2,
        {"team-1": "130", "team-2": "90", "team-3": "100", "team-4": "80"},
    )

    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    team_ids = _team_id_map(session, league_id)
    by_team = {row.team_id: row for row in projected.overall}
    assert (
        by_team[team_ids["team-1"]].wins,
        by_team[team_ids["team-1"]].losses,
        by_team[team_ids["team-1"]].ties,
    ) == (1, 0, 0)
    assert (
        by_team[team_ids["team-4"]].wins,
        by_team[team_ids["team-4"]].losses,
        by_team[team_ids["team-4"]].ties,
    ) == (0, 1, 0)
    assert projected.projection is not None
    assert (
        next(
            team for team in projected.projection.teams if team.team_id == team_ids["team-1"]
        ).opponent_team_id
        is None
    )


def test_projected_week_with_a_missing_pairing_is_unavailable(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A projected week that does not list every team is inconsistent, not partially filled."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    _, session = db
    with db[0]() as write:
        repository = SyncRepository(write)
        matchups = repository.get_week_matchups(league_id, SEASON, 2)
        repository.delete_matchup(matchups[0])
        write.commit()

    projected = StandingsService(session).get_standings(league_id, SEASON, include_projected=True)

    assert projected.projection is not None
    assert projected.projection.reason == "incomplete_schedule"


def _three_week_provider(*, week_2_complete: bool) -> FakeProvider:
    """Build a 3-week provider whose later state finalizes week 2 and projects week 3."""
    league = LeagueDTO(
        external_id=LEAGUE,
        name="Projection League",
        metadata={"regular_season_length": 3, "playoff_team_count": 4},
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
    matchups = {
        1: [
            MatchupDTO(
                1,
                MatchupSideDTO("team-1", Decimal("120.00")),
                MatchupSideDTO("team-4", Decimal("90.00")),
                False,
                True,
            ),
            MatchupDTO(
                1,
                MatchupSideDTO("team-2", Decimal("110.00")),
                MatchupSideDTO("team-3", Decimal("100.00")),
                False,
                True,
            ),
        ],
        2: [
            MatchupDTO(
                2,
                MatchupSideDTO("team-1", Decimal("130.00") if week_2_complete else None),
                MatchupSideDTO("team-3", Decimal("100.00") if week_2_complete else None),
                False,
                week_2_complete,
            ),
            MatchupDTO(
                2,
                MatchupSideDTO("team-2", Decimal("90.00") if week_2_complete else None),
                MatchupSideDTO("team-4", Decimal("80.00") if week_2_complete else None),
                False,
                week_2_complete,
            ),
        ],
        3: [
            MatchupDTO(
                3,
                MatchupSideDTO("team-1", None),
                MatchupSideDTO("team-2", None),
                False,
                False,
            ),
            MatchupDTO(
                3,
                MatchupSideDTO("team-3", None),
                MatchupSideDTO("team-4", None),
                False,
                False,
            ),
        ],
    }
    projections = (
        {
            (LEAGUE, SEASON): {
                3: [
                    ProjectionDTO(
                        3,
                        ProjectionSideDTO("team-1", Decimal("110.00")),
                        ProjectionSideDTO("team-2", Decimal("105.00")),
                        False,
                    ),
                    ProjectionDTO(
                        3,
                        ProjectionSideDTO("team-3", Decimal("100.00")),
                        ProjectionSideDTO("team-4", Decimal("95.00")),
                        False,
                    ),
                ]
            }
        }
        if week_2_complete
        else None
    )
    return FakeProvider(
        {(LEAGUE, SEASON): (league, owners, teams, matchups, WeekStatus(1))},
        projections=projections,
    )


def test_active_week_finalizes_and_projects_the_next_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A just-completed week is finalized before the next week's projections are stored."""
    initial = _three_week_provider(week_2_complete=False)
    league_id = _sync(db, initial)
    _, session = db
    _add_credentials(session, league_id)

    later = _three_week_provider(week_2_complete=True)
    summary = SyncService(later, session, clock=lambda: FIXED_NOW).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    assert summary.completed_week == 2
    assert summary.active_week == 3
    assert summary.projections_stored == 4
    with db[0]() as check:
        assert StandingsService(check).get_standings(league_id, SEASON).completed_weeks == 2
        assert len(SyncRepository(check).get_week_projections(league_id, SEASON, 3)) == 4


def test_full_season_sync_refreshes_the_active_week_projections(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A full-season sync (the admin refresh path) also stores the active-week projections."""
    provider, _ = _seed()
    league_id = _sync(db, provider)

    with db[0]() as check:
        repository = SyncRepository(check)
        team_ids = _team_id_map(check, league_id)
        rows = repository.get_week_projections(league_id, SEASON, 2)
        assert {row.team_id: row.points for row in rows} == {
            team_ids["team-1"]: Decimal("130.00"),
            team_ids["team-2"]: Decimal("90.00"),
            team_ids["team-3"]: Decimal("100.00"),
            team_ids["team-4"]: Decimal("80.00"),
        }
        season = repository.get_league_season(league_id, SEASON)
        assert season is not None
        assert season.projections_refreshed_at is not None


def test_full_season_sync_clears_projections_when_the_season_is_complete(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A complete season has no active week, so a full sync leaves no projections behind."""
    provider, _ = _seed(week_2_complete=True)
    league_id = _sync(db, provider)

    with db[0]() as check:
        assert SyncRepository(check).get_week_projections(league_id, SEASON, 2) == []


def test_full_season_sync_skips_projections_for_a_historical_season(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """ESPN projections are current-season only, so a historical refresh leaves them alone."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    with db[0]() as write:
        SyncRepository(write).upsert_league_season(
            league_id, 2025, {"regular_season_length": 2, "playoff_team_count": 4}
        )
        write.commit()
    historical_provider, _ = _seed(season=2025)
    with db[0]() as session:
        summary = SyncService(historical_provider, session, clock=lambda: FIXED_NOW).sync_league(
            LeagueRef(external_id=LEAGUE),
            "fake",
            2025,
        )
        session.commit()
        assert summary.season == 2025
        assert SyncRepository(session).get_week_projections(league_id, 2025, 2) == []


def test_full_season_sync_survives_a_projection_provider_failure(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A projection-only provider failure does not undo a successful league sync."""
    provider, _ = _seed()

    class ProjectionFailure(FakeProvider):
        def fetch_projections(
            self, league_ref: LeagueRef, season: int, week: int
        ) -> list[ProjectionDTO]:
            raise RuntimeError("box scores unavailable")

    failing = ProjectionFailure(
        {
            (LEAGUE, SEASON): (
                LeagueDTO(
                    external_id=LEAGUE,
                    name="Projection League",
                    metadata={"regular_season_length": 2, "playoff_team_count": 4},
                ),
                provider.fetch_owners(LeagueRef(external_id=LEAGUE), SEASON),
                provider.fetch_teams(LeagueRef(external_id=LEAGUE), SEASON),
                {
                    1: provider.fetch_matchups(LeagueRef(external_id=LEAGUE), SEASON, 1),
                    2: provider.fetch_matchups(LeagueRef(external_id=LEAGUE), SEASON, 2),
                },
                WeekStatus(last_completed_week=1),
            )
        }
    )
    league_id = _sync(db, failing)

    with db[0]() as check:
        repository = SyncRepository(check)
        assert repository.get_teams(league_id, SEASON)
        assert repository.get_week_scores(league_id, SEASON, 1)
        assert repository.get_week_projections(league_id, SEASON, 2) == []


def test_projected_wapdate_offers_a_new_period(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A projected week that starts a new period offers that period as current."""
    provider, _ = _seed(week_2_complete=True)
    league_id = _sync(db, provider)
    session = db[1]
    with db[0]() as write:
        repository = SyncRepository(write)
        repository.upsert_league_season(
            league_id,
            SEASON,
            {"regular_season_length": 5, "playoff_team_count": 4},
        )
        teams = {team.external_id: team.id for team in repository.get_teams(league_id, SEASON)}
        for week in (3, 4, 5):
            complete = week != 5
            repository.upsert_matchup(
                league_id, SEASON, week, teams["team-1"], teams["team-2"], False, complete
            )
            repository.upsert_matchup(
                league_id, SEASON, week, teams["team-3"], teams["team-4"], False, complete
            )
            if complete:
                for external_id, points in (
                    ("team-1", "120"),
                    ("team-2", "100"),
                    ("team-3", "110"),
                    ("team-4", "90"),
                ):
                    repository.upsert_score(
                        teams[external_id],
                        league_id,
                        SEASON,
                        week,
                        Decimal(points),
                    )
        write.commit()
    _store_projections(
        db,
        league_id,
        5,
        {"team-1": "130", "team-2": "90", "team-3": "100", "team-4": "80"},
    )

    wapdate = StandingsService(session).get_wapdate(league_id, SEASON, include_projected=True)

    assert [period.period for period in wapdate.periods] == [1, 2]
    period_two = wapdate.periods[1]
    assert period_two.status == "current"
    assert period_two.weeks == (5,)
    assert len(period_two.rows) == 4


def test_active_week_does_not_touch_last_refreshed_at(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """The 15-minute path updates projections_refreshed_at, not the full-season timestamp."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id)
    later = FIXED_NOW + timedelta(hours=1)
    provider.set_projections(LeagueRef(external_id=LEAGUE), SEASON, {2: _valid_projection_list()})

    SyncService(provider, session, clock=lambda: later).sync_active_week(
        LeagueRef(external_id=LEAGUE), "fake", SEASON
    )
    session.commit()

    with db[0]() as check:
        season = SyncRepository(check).get_league_season(league_id, SEASON)
        assert season is not None
        assert season.last_refreshed_at is not None
        assert season.last_refreshed_at.replace(tzinfo=UTC) == FIXED_NOW
        assert season.projections_refreshed_at is not None
        assert season.projections_refreshed_at.replace(tzinfo=UTC) == later


def test_all_credential_holders_are_tried(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """All holders are attempted, with no arbitrary cap that can hide a valid one."""
    provider, _ = _seed(with_projections=False)
    league_id = _sync(db, provider)
    _, session = db
    _add_credentials(session, league_id, count=12)

    attempts = 0

    def factory(**_: str | None):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts < 12:
            raise ProviderAuthError("rejected")
        return provider

    class NoShuffle(random.Random):
        def shuffle(self, _items: list[tuple[str, str]]) -> None:
            return None

    results = refresh_active_weeks(
        session_factory=db[0],
        provider_id="fake",
        provider_factory=factory,
        clock=lambda: FIXED_NOW,
        random_source=NoShuffle(),
    )

    assert [result.status for result in results] == ["ok"]
    assert attempts == 12


def test_projected_view_rejects_a_missing_later_week(
    db: tuple[sessionmaker[Session], Session],
) -> None:
    """A missing schedule after the first incomplete week makes the projected view unavailable."""
    provider, _ = _seed()
    league_id = _sync(db, provider)
    with db[0]() as write:
        SyncRepository(write).upsert_league_season(
            league_id,
            SEASON,
            {"regular_season_length": 3, "playoff_team_count": 4},
        )
        write.commit()

    projected = StandingsService(db[1]).get_standings(league_id, SEASON, include_projected=True)

    assert projected.projection is not None
    assert projected.projection.week is None
    assert projected.projection.reason == "no_active_week"
