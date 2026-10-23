"""Service acceptance tests for Elo history and settings (AC-Elo-*).

Every fixture is written through the real sync service and the in-memory ``FakeProvider``. No test
calls ESPN or any network service. The tests focus on the stored-data rules the pure domain cannot
see: latest names/owners, aliases, season ordering, cup-week flags, excluded playoff/incomplete
weeks, unrated teams, deleted seasons, and per-league settings.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth_repositories import MembershipRepository, UserRepository
from app.db.base import Base
from app.db.models import LeagueSeason, Matchup, Score, Team
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
from app.providers.fake import FakeProvider
from app.services.elo_service import (
    EloLeagueNotFoundError,
    EloService,
    InvalidEloConfigError,
)
from app.services.league_service import AdminRequiredError, LeagueUser, NotAMemberError
from app.services.sync_service import SyncService

LEAGUE_EXTERNAL = "elo-fixture-league"
ADMIN = LeagueUser(user_id=1, role="admin")
MEMBER = LeagueUser(user_id=2, role="member")


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite database session for each test."""
    engine = create_engine(os.environ.get("REPOSITORY_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@dataclass(frozen=True)
class SeasonSeed:
    """One season's teams, matchups, and regular-season length."""

    teams: tuple[tuple[str, str, str], ...]  # (external_id, name, owner_external_id)
    weeks: Mapping[int, Sequence[MatchupDTO]]
    regular_season_length: int


@dataclass(frozen=True)
class Seeded:
    """The stored league and a season-keyed team id lookup."""

    league_id: int
    team_ids: Mapping[tuple[int, str], int]


def matchup(
    week: int,
    home: str,
    home_points: str,
    away: str | None,
    away_points: str | None,
    *,
    is_playoff: bool = False,
    is_complete: bool = True,
) -> MatchupDTO:
    """Build one normalized matchup; away=None is a bye."""
    away_side = (
        MatchupSideDTO(team_external_id=away, points=Decimal(away_points))
        if away is not None and away_points is not None
        else None
    )
    return MatchupDTO(
        week=week,
        home=MatchupSideDTO(team_external_id=home, points=Decimal(home_points)),
        away=away_side,
        is_playoff=is_playoff,
        is_complete=is_complete,
    )


def seed_league(
    session: Session,
    seasons: Mapping[int, SeasonSeed],
    *,
    cup_weeks: Mapping[int, int] | None = None,
) -> Seeded:
    """Sync every supplied season through FakeProvider and optionally set cup weeks."""
    provider_seed: dict[
        tuple[str, int],
        tuple[LeagueDTO, list[OwnerDTO], list[TeamDTO], dict[int, list[MatchupDTO]], WeekStatus],
    ] = {}
    for season, spec in seasons.items():
        owners: dict[str, OwnerDTO] = {}
        teams: list[TeamDTO] = []
        for external_id, name, owner_external_id in spec.teams:
            owners.setdefault(
                owner_external_id,
                OwnerDTO(
                    external_id=owner_external_id,
                    display_name=f"Owner {owner_external_id}",
                ),
            )
            teams.append(
                TeamDTO(
                    external_id=external_id,
                    name=name,
                    division=None,
                    owner_external_id=owner_external_id,
                )
            )
        provider_seed[(LEAGUE_EXTERNAL, season)] = (
            LeagueDTO(
                external_id=LEAGUE_EXTERNAL,
                name="Elo Fixture League",
                metadata={
                    "regular_season_length": spec.regular_season_length,
                    "team_count": len(spec.teams),
                },
            ),
            list(owners.values()),
            teams,
            {week: list(items) for week, items in spec.weeks.items()},
            WeekStatus(last_completed_week=max(spec.weeks) if spec.weeks else None),
        )

    provider = FakeProvider(provider_seed)
    sync = SyncService(provider, session)
    league_id: int | None = None
    for season, spec in sorted(seasons.items()):
        summary = sync.sync_league(
            LeagueRef(external_id=LEAGUE_EXTERNAL),
            "fake",
            season,
            weeks=sorted(spec.weeks),
        )
        league_id = summary.league_id
    assert league_id is not None
    session.commit()

    repository = SyncRepository(session)
    for season, cup_week in (cup_weeks or {}).items():
        row = repository.get_league_season(league_id, season)
        assert row is not None
        row.cup_week = cup_week
    session.commit()

    team_ids: dict[tuple[int, str], int] = {}
    for season in seasons:
        for team in repository.get_teams(league_id, season):
            team_ids[(season, team.external_id)] = team.id
    return Seeded(league_id=league_id, team_ids=team_ids)


def create_user(session: Session, email: str, *, league_id: int | None, role: str) -> int:
    """Create an account (as admin or member) and optionally its membership."""
    user = UserRepository(session).create(email, "unused-password-hash")
    user.role = role
    if league_id is not None:
        MembershipRepository(session).create(user.id, league_id)
    session.commit()
    return user.id


def two_team_season(
    season: int,
    *,
    teams: tuple[tuple[str, str, str], ...] = (
        ("team-a", "Alpha", "owner-a"),
        ("team-b", "Bravo", "owner-b"),
    ),
    weeks: Mapping[int, Sequence[MatchupDTO]] | None = None,
    regular_season_length: int = 2,
) -> SeasonSeed:
    """Build a simple two-team season with one completed week by default."""
    return SeasonSeed(
        teams=teams,
        weeks=weeks or {1: [matchup(1, "team-a", "120", "team-b", "100")]},
        regular_season_length=regular_season_length,
    )


# ---------------------------------------------------------------------------
# History assembly and stable ordering
# ---------------------------------------------------------------------------


def test_AC_Elo_30_service_returns_aligned_series_and_ordered_seasons(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2024: two_team_season(
                2024,
                weeks={
                    1: [matchup(1, "team-a", "120", "team-b", "100")],
                    2: [matchup(2, "team-b", "130", "team-a", "90")],
                },
            ),
            2025: two_team_season(2025),
        },
    )

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")

    assert history.seasons == (2024, 2025)
    assert [(week.season, week.week) for week in history.weeks] == [
        (2024, 1),
        (2024, 2),
        (2025, 1),
    ]
    assert history.season_boundaries[0].season == 2025
    assert history.season_boundaries[0].week_index == 2
    assert [team.team_key for team in history.teams] == ["fake:team-a", "fake:team-b"]
    for team in history.teams:
        assert len(team.history.series) == len(history.weeks)
    assert history.teams[0].history.first_season == 2024


def test_AC_Elo_31_service_uses_the_latest_name_owner_and_aliases(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2024: SeasonSeed(
                teams=(("team-a", "Old Name", "owner-old"), ("team-b", "Bravo", "owner-b")),
                weeks={1: [matchup(1, "team-a", "120", "team-b", "100")]},
                regular_season_length=1,
            ),
            2025: SeasonSeed(
                teams=(("team-a", "New Name", "owner-new"), ("team-b", "Bravo", "owner-b")),
                weeks={1: [matchup(1, "team-a", "120", "team-b", "100")]},
                regular_season_length=1,
            ),
        },
    )

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")
    alpha = next(team for team in history.teams if team.team_key == "fake:team-a")

    assert alpha.name == "New Name"
    assert alpha.owner_name == "Owner owner-new"
    assert alpha.aliases == ("Old Name",)
    assert alpha.history.rated_weeks == 2
    # The franchise keeps its rating across the rename: the 2025 baseline is a regression of the
    # 2024 result, not a fresh 1500.
    assert alpha.history.seasons[1].start_rating > Decimal("1500")


def test_AC_Elo_32_service_marks_cup_weeks_and_mode_differences(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2026: SeasonSeed(
                teams=(("team-a", "Alpha", "owner-a"), ("team-b", "Bravo", "owner-b")),
                weeks={
                    1: [matchup(1, "team-a", "120", "team-b", "100")],
                    2: [matchup(2, "team-a", "300", "team-b", "10")],
                },
                regular_season_length=2,
            )
        },
        cup_weeks={2026: 2},
    )

    service = EloService(session)
    actual = service.get_history(seeded.league_id, "actual_schedule")
    round_robin = service.get_history(seeded.league_id, "round_robin")

    assert [point.is_cup_week for point in actual.weeks] == [False, True]
    assert [point.rated for point in actual.weeks] == [True, False]
    assert [point.rated for point in round_robin.weeks] == [True, True]
    actual_a = next(team for team in actual.teams if team.team_key == "fake:team-a")
    round_robin_a = next(team for team in round_robin.teams if team.team_key == "fake:team-a")
    assert actual_a.history.series[1] == actual_a.history.series[0]
    assert round_robin_a.history.series[1] != round_robin_a.history.series[0]


def test_AC_Elo_33_service_excludes_playoff_and_incomplete_weeks(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2026: SeasonSeed(
                teams=(("team-a", "Alpha", "owner-a"), ("team-b", "Bravo", "owner-b")),
                weeks={
                    1: [matchup(1, "team-a", "120", "team-b", "100")],
                    2: [
                        matchup(
                            2,
                            "team-a",
                            "120",
                            "team-b",
                            "100",
                            is_complete=False,
                        )
                    ],
                    3: [
                        matchup(
                            3,
                            "team-a",
                            "120",
                            "team-b",
                            "100",
                            is_playoff=True,
                        )
                    ],
                    4: [matchup(4, "team-b", "120", "team-a", "100")],
                },
                regular_season_length=4,
            )
        },
    )

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")

    assert [week.week for week in history.weeks] == [1, 4]
    assert [point.rated for point in history.weeks] == [True, True]


def test_AC_Elo_34_service_lists_teams_without_rated_weeks(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2026: SeasonSeed(
                teams=(
                    ("team-a", "Alpha", "owner-a"),
                    ("team-b", "Bravo", "owner-b"),
                    ("team-c", "Bye Team", "owner-c"),
                ),
                weeks={
                    1: [
                        matchup(1, "team-a", "120", "team-b", "100"),
                        matchup(1, "team-c", "90", None, None),
                    ]
                },
                regular_season_length=1,
            )
        },
    )

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")

    assert [team.team_key for team in history.teams] == ["fake:team-a", "fake:team-b"]
    assert [(team.team_key, team.name) for team in history.unrated_teams] == [
        ("fake:team-c", "Bye Team")
    ]
    assert history.unrated_teams[0].reason == "No rated matchups yet"


def test_AC_Elo_35_deleting_a_season_recomputes_later_history(session: Session) -> None:
    seeded = seed_league(
        session,
        {2024: two_team_season(2024), 2025: two_team_season(2025)},
    )
    service = EloService(session)
    before = service.get_history(seeded.league_id, "actual_schedule")
    before_alpha = next(team for team in before.teams if team.team_key == "fake:team-a")
    assert before_alpha.history.seasons[1].start_rating > Decimal("1500")

    session.execute(delete(Score).where(Score.league_id == seeded.league_id, Score.season == 2024))
    session.execute(
        delete(Matchup).where(Matchup.league_id == seeded.league_id, Matchup.season == 2024)
    )
    session.execute(delete(Team).where(Team.league_id == seeded.league_id, Team.season == 2024))
    session.execute(
        delete(LeagueSeason).where(
            LeagueSeason.league_id == seeded.league_id, LeagueSeason.season == 2024
        )
    )
    session.commit()

    after = service.get_history(seeded.league_id, "actual_schedule")
    after_alpha = next(team for team in after.teams if team.team_key == "fake:team-a")

    assert after.seasons == (2025,)
    assert [week.season for week in after.weeks] == [2025]
    assert after_alpha.history.seasons[0].start_rating == Decimal("1500")


def test_AC_Elo_36_new_franchise_mid_history_has_leading_nulls(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2024: two_team_season(2024),
            2025: SeasonSeed(
                teams=(
                    ("team-a", "Alpha", "owner-a"),
                    ("team-b", "Bravo", "owner-b"),
                    ("team-c", "Charlie", "owner-c"),
                ),
                weeks={1: [matchup(1, "team-c", "120", "team-a", "100")]},
                regular_season_length=1,
            ),
        },
    )

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")
    charlie = next(team for team in history.teams if team.team_key == "fake:team-c")

    assert charlie.history.series[0] is None
    assert charlie.history.series[1] is not None
    assert charlie.history.seasons[0].start_rating == Decimal("1500")


def test_AC_Elo_37_empty_league_returns_an_empty_history(session: Session) -> None:
    repository = SyncRepository(session)
    league = repository.upsert_league("fake", "empty-league", "Empty", {}, "membership").row
    session.commit()

    history = EloService(session).get_history(league.id, "round_robin")

    assert history.weeks == ()
    assert history.teams == ()
    assert history.seasons == ()
    with pytest.raises(EloLeagueNotFoundError):
        EloService(session).get_history(999, "round_robin")


def test_AC_Elo_38_invalid_season_metadata_warns_instead_of_failing(session: Session) -> None:
    repository = SyncRepository(session)
    league = repository.upsert_league("fake", "bad-season", "Bad", {}, "membership").row
    repository.upsert_league_season(league.id, 2026, {})
    repository.upsert_team(league.id, 2026, "team-a", "Alpha", None, None)
    session.commit()

    history = EloService(session).get_history(league.id, "actual_schedule")

    assert history.weeks == ()
    assert history.seasons == ()
    assert history.warnings[0].code == "missing_regular_season_length"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_AC_Elo_39_settings_default_then_persist_round_trip(session: Session) -> None:
    seeded = seed_league(session, {2026: two_team_season(2026, regular_season_length=1)})
    admin_id = create_user(session, "admin@example.com", league_id=seeded.league_id, role="admin")
    admin = LeagueUser(user_id=admin_id, role="admin")
    service = EloService(session)

    defaults = service.get_config(admin, seeded.league_id)
    assert defaults.starting_rating == Decimal("1500")
    assert defaults.k_factor == Decimal("24")

    saved = service.update_config(
        admin,
        seeded.league_id,
        starting_rating=Decimal("1600"),
        k_factor=Decimal("32"),
        margin_weight=Decimal("0.5"),
        margin_cap=Decimal("40"),
        season_regression=Decimal("0.5"),
    )
    service.commit()

    assert saved.starting_rating == Decimal("1600")
    reloaded = EloService(session).get_config(admin, seeded.league_id)
    assert reloaded.k_factor == Decimal("32")
    assert reloaded.margin_cap == Decimal("40")
    assert reloaded.season_regression == Decimal("0.5")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starting_rating", Decimal("999")),
        ("k_factor", Decimal("101")),
        ("margin_weight", Decimal("2")),
        ("margin_cap", Decimal("0")),
        ("season_regression", Decimal("-1")),
    ],
)
def test_AC_Elo_40_settings_reject_out_of_range_values(
    session: Session, field: str, value: Decimal
) -> None:
    seeded = seed_league(session, {2026: two_team_season(2026, regular_season_length=1)})
    admin_id = create_user(session, "admin@example.com", league_id=seeded.league_id, role="admin")
    admin = LeagueUser(user_id=admin_id, role="admin")
    service = EloService(session)
    values: dict[str, Decimal] = {
        "starting_rating": Decimal("1500"),
        "k_factor": Decimal("24"),
        "margin_weight": Decimal("0.25"),
        "margin_cap": Decimal("50"),
        "season_regression": Decimal("0.3"),
    }
    values[field] = value

    with pytest.raises(InvalidEloConfigError):
        service.update_config(admin, seeded.league_id, **values)


def test_AC_Elo_41_settings_require_membership_and_admin(session: Session) -> None:
    seeded = seed_league(session, {2026: two_team_season(2026, regular_season_length=1)})
    member_id = create_user(
        session, "member@example.com", league_id=seeded.league_id, role="member"
    )
    member = LeagueUser(user_id=member_id, role="member")
    outsider = create_user(session, "outsider@example.com", league_id=None, role="admin")
    service = EloService(session)

    with pytest.raises(AdminRequiredError):
        service.get_config(member, seeded.league_id)
    with pytest.raises(NotAMemberError):
        service.get_config(LeagueUser(user_id=outsider, role="admin"), seeded.league_id)


def test_AC_Elo_42_service_warns_for_missing_scores_without_failing(session: Session) -> None:
    seeded = seed_league(
        session,
        {
            2026: SeasonSeed(
                teams=(("team-a", "Alpha", "owner-a"), ("team-b", "Bravo", "owner-b")),
                weeks={
                    1: [matchup(1, "team-a", "120", "team-b", "100")],
                    2: [matchup(2, "team-b", "130", "team-a", "90")],
                },
                regular_season_length=2,
            )
        },
    )
    session.execute(
        delete(Score).where(
            Score.league_id == seeded.league_id,
            Score.season == 2026,
            Score.week == 1,
            Score.team_id == seeded.team_ids[(2026, "team-b")],
        )
    )
    session.commit()

    service = EloService(session)
    actual = service.get_history(seeded.league_id, "actual_schedule")
    round_robin = service.get_history(seeded.league_id, "round_robin")

    assert [warning.code for warning in actual.warnings] == ["missing_score"]
    assert [warning.code for warning in round_robin.warnings] == ["missing_score"]
    assert [point.rated for point in actual.weeks] == [False, True]
    assert [point.rated for point in round_robin.weeks] == [False, True]


def test_AC_Elo_43_service_warns_for_a_season_without_teams(session: Session) -> None:
    seeded = seed_league(session, {2026: two_team_season(2026, regular_season_length=1)})
    repository = SyncRepository(session)
    repository.upsert_league_season(seeded.league_id, 2025, {"regular_season_length": 14})
    session.commit()

    history = EloService(session).get_history(seeded.league_id, "actual_schedule")

    assert history.seasons == (2026,)
    assert [warning.code for warning in history.warnings] == ["no_teams"]
