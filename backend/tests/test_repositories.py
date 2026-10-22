import os
from collections.abc import Iterator
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import League, LeagueSeason, Matchup, Owner, Score, Team
from app.db.repositories import SyncRepository, WeeklyVPValues


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated test database and a caller-owned ORM session.

    SQLite is the default. Set REPOSITORY_TEST_DATABASE_URL to the worktree-local PostgreSQL URL
    to run this same repository suite against PostgreSQL.
    """
    engine = create_engine(os.environ.get("REPOSITORY_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_week(repository: SyncRepository) -> tuple[int, int, int]:
    """Create one league, two teams, one matchup, and their weekly scores."""
    league = repository.upsert_league("fake", "league-1", "League", {}, "config").row
    owner = repository.upsert_owner(league.id, "owner-1", "Owner").row
    home = repository.upsert_team(league.id, 2025, "team-1", "Home", "East", owner.id).row
    away = repository.upsert_team(league.id, 2025, "team-2", "Away", "West", owner.id).row
    repository.upsert_matchup(league.id, 2025, 1, home.id, away.id, False, True)
    repository.upsert_score(home.id, league.id, 2025, 1, Decimal("120.00"))
    repository.upsert_score(away.id, league.id, 2025, 1, Decimal("99.25"))
    return league.id, home.id, away.id


def test_repository_upserts_are_natural_key_idempotent_and_update_values(
    session: Session,
) -> None:
    """Repeated natural keys update values without creating duplicate entity rows."""
    repository = SyncRepository(session)
    league = repository.upsert_league("fake", "league-1", "League", {"teams": 2}, "ref")
    same_league = repository.upsert_league("fake", "league-1", "League", {"teams": 2}, "ref")
    owner = repository.upsert_owner(league.row.id, "owner-1", "Owner")
    same_owner = repository.upsert_owner(league.row.id, "owner-1", "Owner")
    team = repository.upsert_team(league.row.id, 2025, "team-1", "Home", "East", owner.row.id)
    same_team = repository.upsert_team(league.row.id, 2025, "team-1", "Home", "East", owner.row.id)
    matchup = repository.upsert_matchup(league.row.id, 2025, 1, team.row.id, None, False, False)
    same_matchup = repository.upsert_matchup(
        league.row.id, 2025, 1, team.row.id, None, False, False
    )
    score = repository.upsert_score(team.row.id, league.row.id, 2025, 1, Decimal("100.00"))
    same_score = repository.upsert_score(team.row.id, league.row.id, 2025, 1, Decimal("100.00"))

    assert league.changed and owner.changed and team.changed and matchup.changed and score.changed
    assert not any(
        result.changed for result in (same_league, same_owner, same_team, same_matchup, same_score)
    )
    assert same_league.row.id == league.row.id
    assert same_owner.row.id == owner.row.id
    assert same_team.row.id == team.row.id
    assert same_matchup.row.id == matchup.row.id
    assert same_score.row.id == score.row.id
    for model in (League, Owner, Team, Matchup, Score):
        assert session.scalar(select(func.count()).select_from(model)) == 1

    changed = repository.upsert_league("fake", "league-1", "Renamed", {"teams": 3}, "ref-2")
    changed_owner = repository.upsert_owner(league.row.id, "owner-1", "New Owner")
    changed_team = repository.upsert_team(league.row.id, 2025, "team-1", "New Home", None, None)
    changed_matchup = repository.upsert_matchup(
        league.row.id, 2025, 1, team.row.id, None, True, True
    )
    assert changed.changed and changed_owner.changed and changed_team.changed
    assert changed_matchup.changed
    assert changed.row.name == "Renamed"
    assert changed_owner.row.display_name == "New Owner"
    assert changed_team.row.division is None and changed_team.row.owner_id is None
    assert changed_matchup.row.is_playoff and changed_matchup.row.is_complete


def test_repository_score_upsert_reports_score_corrections(session: Session) -> None:
    """A corrected Decimal score updates the existing row and preserves VP for recompute."""
    repository = SyncRepository(session)
    league_id, home_id, _ = _seed_week(repository)
    original = repository.get_week_scores(league_id, 2025, 1)[0]
    original.victory_points = Decimal("2.000000")
    session.flush()

    correction = repository.upsert_score(home_id, league_id, 2025, 1, Decimal("121.75"))

    assert correction.changed
    assert correction.row.points == Decimal("121.75")
    assert correction.row.victory_points == Decimal("2.000000")
    unchanged = repository.upsert_score(home_id, league_id, 2025, 1, Decimal("121.75"))
    assert not unchanged.changed
    assert session.scalar(select(func.count()).select_from(Score)) == 2


def test_repository_loads_matchups_and_scores_for_a_week(session: Session) -> None:
    """Week reads return only the requested league season week in stable order."""
    repository = SyncRepository(session)
    league_id, home_id, away_id = _seed_week(repository)
    other_week = repository.upsert_score(home_id, league_id, 2025, 2, Decimal("1.00"))

    matchups = repository.get_week_matchups(league_id, 2025, 1)
    scores = repository.get_week_scores(league_id, 2025, 1)

    assert [(row.home_team_id, row.away_team_id) for row in matchups] == [(home_id, away_id)]
    assert [(row.team_id, row.points) for row in scores] == [
        (home_id, Decimal("120.00")),
        (away_id, Decimal("99.25")),
    ]
    assert other_week.row not in scores
    assert [team.id for team in repository.get_teams(league_id, 2025)] == [home_id, away_id]


def test_repository_natural_key_lookups_return_rows_or_none(session: Session) -> None:
    """League and owner lookup methods distinguish absent keys from stored rows."""
    repository = SyncRepository(session)
    assert repository.get_league("fake", "missing") is None
    league_id, _, _ = _seed_week(repository)
    assert repository.get_league("fake", "league-1") is not None
    assert repository.get_owner(league_id, "owner-1") is not None
    assert repository.get_owner(league_id, "missing") is None


def test_repository_league_season_upsert_is_idempotent_and_reports_changes(
    session: Session,
) -> None:
    """Repeated league-season upserts reuse one row and report only real settings changes."""
    repository = SyncRepository(session)
    league_id = repository.upsert_league("fake", "league-1", "League", {}, "config").row.id

    created = repository.upsert_league_season(league_id, 2025, {"regular_season_length": 14})
    repeated = repository.upsert_league_season(league_id, 2025, {"regular_season_length": 14})

    assert created.changed
    assert not repeated.changed
    assert repeated.row.id == created.row.id
    assert created.row.season == 2025
    assert repository.get_league_season(league_id, 2025).league_season_metadata == {
        "regular_season_length": 14
    }

    updated = repository.upsert_league_season(
        league_id, 2025, {"regular_season_length": 15, "team_count": 12}
    )

    assert updated.changed
    assert updated.row.id == created.row.id
    assert updated.row.league_season_metadata == {
        "regular_season_length": 15,
        "team_count": 12,
    }
    assert session.scalar(select(func.count()).select_from(LeagueSeason)) == 1


def test_AC_DB_09_league_season_upsert_preserves_an_existing_cup_week(session: Session) -> None:
    """A sync rewrites provider metadata but never clears the season's admin-chosen cup week."""
    repository = SyncRepository(session)
    league_id = repository.upsert_league("fake", "league-1", "League", {}, "config").row.id
    row = repository.upsert_league_season(league_id, 2026, {"regular_season_length": 14}).row
    row.cup_week = 7
    session.flush()

    updated = repository.upsert_league_season(league_id, 2026, {"regular_season_length": 15})

    assert updated.changed
    assert updated.row.cup_week == 7
    stored = repository.get_league_season(league_id, 2026)
    assert stored is not None
    assert stored.cup_week == 7


def test_league_season_metadata_defaults_to_an_empty_object(session: Session) -> None:
    """A league season created without settings stores an empty JSON object."""
    league_id = SyncRepository(session).upsert_league("fake", "league-1", "League", {}, "c").row.id
    row = LeagueSeason(league_id=league_id, season=2026)

    session.add(row)
    session.flush()

    assert row.league_season_metadata == {}


def test_repository_league_seasons_are_independent_of_each_other(session: Session) -> None:
    """Refreshing one season's settings leaves every other stored season untouched."""
    repository = SyncRepository(session)
    league_id = repository.upsert_league("fake", "league-1", "League", {}, "config").row.id

    repository.upsert_league_season(
        league_id, 2024, {"team_count": 10, "division_count": 2, "scoring_type": "standard"}
    )
    repository.upsert_league_season(
        league_id, 2025, {"team_count": 12, "division_count": 3, "scoring_type": "ppr"}
    )
    repository.upsert_league_season(league_id, 2025, {"team_count": 12, "playoff_week": 16})

    assert repository.get_league_season(league_id, 2024).league_season_metadata == {
        "team_count": 10,
        "division_count": 2,
        "scoring_type": "standard",
    }
    assert repository.get_league_season(league_id, 2025).league_season_metadata == {
        "team_count": 12,
        "playoff_week": 16,
    }


def test_repository_league_season_lookups_return_rows_or_none(session: Session) -> None:
    """Season reads return the requested season only, in stable ascending season order."""
    repository = SyncRepository(session)
    league_id = repository.upsert_league("fake", "league-1", "League", {}, "config").row.id
    other_league_id = repository.upsert_league("fake", "league-2", "Other", {}, "config").row.id
    for season in (2025, 2023, 2024):
        repository.upsert_league_season(league_id, season, {"team_count": season % 10})
    repository.upsert_league_season(other_league_id, 2024, {"team_count": 8})

    assert repository.get_league_season(league_id, 2022) is None
    assert repository.get_league_season(league_id, 2024).league_season_metadata == {"team_count": 4}
    assert repository.get_league_season(other_league_id, 2024).league_season_metadata == {
        "team_count": 8
    }
    assert [row.season for row in repository.list_league_seasons(league_id)] == [2023, 2024, 2025]
    assert [row.season for row in repository.list_league_seasons(other_league_id)] == [2024]
    assert [row.season for row in repository.get_league("fake", "league-1").seasons] == [
        2023,
        2024,
        2025,
    ]


def test_league_season_natural_key_rejects_a_duplicate_season(session: Session) -> None:
    """The (league_id, season) unique constraint blocks a second row for the same season."""
    repository = SyncRepository(session)
    league_id = repository.upsert_league("fake", "league-1", "League", {}, "config").row.id
    repository.upsert_league_season(league_id, 2025, {"team_count": 12})
    session.commit()

    session.add(
        LeagueSeason(league_id=league_id, season=2025, league_season_metadata={"team_count": 14})
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    stored = repository.list_league_seasons(league_id)
    assert [row.season for row in stored] == [2025]
    assert stored[0].league_season_metadata == {"team_count": 12}


def test_repository_requires_decimal_values_at_persistence_boundary(session: Session) -> None:
    """Scores and all VP inputs reject values that bypass the Decimal persistence contract."""
    repository = SyncRepository(session)
    with pytest.raises(TypeError, match="points must be Decimal"):
        repository.upsert_score(1, 1, 2025, 1, cast(Decimal, 12.5))

    league_id, home_id, away_id = _seed_week(repository)
    invalid_values = {
        home_id: WeeklyVPValues(
            cast(Decimal, 1), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        ),
        away_id: WeeklyVPValues(
            Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        ),
    }
    with pytest.raises(TypeError, match="all VP values must be Decimal"):
        repository.persist_week_vp(league_id, 2025, 1, invalid_values)

    repository.persist_week_vp(league_id, 2025, 2, {})


def test_repository_persists_week_total_and_components_for_all_scores(
    session: Session,
) -> None:
    """Every score receives its supplied Decimal total and four component values."""
    repository = SyncRepository(session)
    league_id, home_id, away_id = _seed_week(repository)
    values = {
        home_id: WeeklyVPValues(
            Decimal("2.5"), Decimal("1"), Decimal("1"), Decimal("0.5"), Decimal("0")
        ),
        away_id: WeeklyVPValues(
            Decimal("-1"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("-1")
        ),
    }

    repository.persist_week_vp(league_id, 2025, 1, values)
    persisted = repository.get_week_scores(league_id, 2025, 1)

    assert [
        (
            row.team_id,
            row.victory_points,
            row.vp_h2h,
            row.vp_top_half,
            row.vp_high,
            row.vp_low,
        )
        for row in persisted
    ] == [
        (
            home_id,
            Decimal("2.500000"),
            Decimal("1.000000"),
            Decimal("1.000000"),
            Decimal("0.500000"),
            Decimal("0.000000"),
        ),
        (
            away_id,
            Decimal("-1.000000"),
            Decimal("0.000000"),
            Decimal("0.000000"),
            Decimal("0.000000"),
            Decimal("-1.000000"),
        ),
    ]


def test_repository_rejects_partial_week_vp_and_leaves_transaction_to_caller(
    session: Session,
) -> None:
    """A partial VP recompute fails, and successful writes remain rollbackable by the caller."""
    repository = SyncRepository(session)
    league_id, home_id, away_id = _seed_week(repository)
    session.commit()
    home_only = {
        home_id: WeeklyVPValues(
            Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        )
    }
    with pytest.raises(ValueError, match="exactly match"):
        repository.persist_week_vp(league_id, 2025, 1, home_only)

    repository.persist_week_vp(
        league_id,
        2025,
        1,
        {
            team_id: WeeklyVPValues(
                Decimal("1"), Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0")
            )
            for team_id in (home_id, away_id)
        },
    )
    assert repository.get_week_scores(league_id, 2025, 1)[0].victory_points == Decimal("1.000000")
    session.rollback()

    assert repository.get_week_scores(league_id, 2025, 1)[0].victory_points == Decimal("0.000000")
