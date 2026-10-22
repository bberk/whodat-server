"""End-to-end tests for the provider-agnostic sync service.

The sync service is tested against the FakeProvider and recorded fixtures only; no live ESPN
calls are made. Every test runs against both SQLite (default) and PostgreSQL (when
REPOSITORY_TEST_DATABASE_URL is set), satisfying AC-DB-05/07 and the sync-→-VP portion of
AC-PR-02.
"""

import os
import unicodedata
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import League, LeagueSeason, Matchup, Owner, Score, Team
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
from app.services.sync_service import (
    PROVIDER_CONFIG_REF,
    LeagueNotFoundError,
    MissingRegularSeasonLengthError,
    SyncError,
    SyncService,
)
from app.validation import MAX_DISPLAY_TEXT_LENGTH

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated database session for each test.

    SQLite is the default; set REPOSITORY_TEST_DATABASE_URL to run against a worktree-local
    PostgreSQL instance.
    """
    url = os.environ.get("REPOSITORY_TEST_DATABASE_URL", "sqlite://")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _league_ref(external_id: str = "league-1") -> LeagueRef:
    return LeagueRef(external_id=external_id)


def _basic_seed(
    *,
    last_completed_week: int | None = 2,
    include_bye: bool = False,
    playoff_week: int | None = None,
    incomplete_week: int | None = None,
    regular_season_length: int | None = 2,
    season: int = 2026,
) -> dict[
    tuple[str, int],
    tuple[LeagueDTO, list[OwnerDTO], list[TeamDTO], dict[int, list[MatchupDTO]], WeekStatus],
]:
    """Build a FakeProvider seed for a 4-team league season with configurable week states.

    ``regular_season_length`` is written into the league metadata the way a real provider does;
    pass None to build a league whose stored metadata omits it. ``season`` keys the seed and the
    metadata, so the same league can be seeded for several seasons in one provider.
    """
    metadata: dict[str, object] = {"teams": 4, "season": season}
    if regular_season_length is not None:
        metadata["regular_season_length"] = regular_season_length
    league = LeagueDTO(
        external_id="league-1",
        name="VP League",
        metadata=metadata,
    )
    owners = [
        OwnerDTO(external_id="owner-1", display_name="Alice"),
        OwnerDTO(external_id="owner-2", display_name="Bob"),
        OwnerDTO(external_id="owner-3", display_name="Carol"),
        OwnerDTO(external_id="owner-4", display_name="Dan"),
    ]
    teams = [
        TeamDTO(external_id="team-1", name="A Team", division="East", owner_external_id="owner-1"),
        TeamDTO(external_id="team-2", name="B Team", division="East", owner_external_id="owner-2"),
        TeamDTO(external_id="team-3", name="C Team", division="West", owner_external_id="owner-3"),
        TeamDTO(external_id="team-4", name="D Team", division="West", owner_external_id="owner-4"),
    ]

    matchups: dict[int, list[MatchupDTO]] = {}
    # Week 1: A vs D, B vs C (all complete, non-playoff)
    matchups[1] = [
        MatchupDTO(
            week=1,
            home=MatchupSideDTO(team_external_id="team-1", points=Decimal("120.00")),
            away=MatchupSideDTO(team_external_id="team-4", points=Decimal("90.00")),
            is_playoff=False,
            is_complete=True,
        ),
        MatchupDTO(
            week=1,
            home=MatchupSideDTO(team_external_id="team-2", points=Decimal("110.00")),
            away=MatchupSideDTO(team_external_id="team-3", points=Decimal("100.00")),
            is_playoff=False,
            is_complete=True,
        ),
    ]
    # Week 2: A vs C, B vs D (all complete, non-playoff)
    matchups[2] = [
        MatchupDTO(
            week=2,
            home=MatchupSideDTO(team_external_id="team-1", points=Decimal("130.00")),
            away=MatchupSideDTO(team_external_id="team-3", points=Decimal("95.00")),
            is_playoff=False,
            is_complete=True,
        ),
        MatchupDTO(
            week=2,
            home=MatchupSideDTO(team_external_id="team-2", points=Decimal("105.00")),
            away=MatchupSideDTO(team_external_id="team-4", points=Decimal("115.00")),
            is_playoff=False,
            is_complete=True,
        ),
    ]
    if include_bye:
        # Week 3: A has a bye (no opponent), B vs C, D vs ???
        # replaced with 3 matchups where one is a bye.
        matchups[3] = [
            MatchupDTO(
                week=3,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("140.00")),
                away=None,  # bye
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=3,
                home=MatchupSideDTO(team_external_id="team-2", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-3", points=Decimal("100.00")),
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=3,
                home=MatchupSideDTO(team_external_id="team-4", points=Decimal("85.00")),
                away=None,  # bye
                is_playoff=False,
                is_complete=True,
            ),
        ]
    if playoff_week is not None:
        matchups[playoff_week] = [
            MatchupDTO(
                week=playoff_week,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("150.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("125.00")),
                is_playoff=True,
                is_complete=True,
            ),
            MatchupDTO(
                week=playoff_week,
                home=MatchupSideDTO(team_external_id="team-3", points=Decimal("110.00")),
                away=MatchupSideDTO(team_external_id="team-4", points=Decimal("95.00")),
                is_playoff=True,
                is_complete=True,
            ),
        ]
    if incomplete_week is not None:
        matchups[incomplete_week] = [
            MatchupDTO(
                week=incomplete_week,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-4", points=Decimal("100.00")),
                is_playoff=False,
                is_complete=False,
            ),
            MatchupDTO(
                week=incomplete_week,
                home=MatchupSideDTO(team_external_id="team-2", points=Decimal("110.00")),
                away=MatchupSideDTO(team_external_id="team-3", points=Decimal("105.00")),
                is_playoff=False,
                is_complete=False,
            ),
        ]

    week_status = WeekStatus(last_completed_week=last_completed_week)
    return {
        ("league-1", season): (league, owners, teams, matchups, week_status),
    }


def _build_provider(
    seed: dict[
        tuple[str, int],
        tuple[LeagueDTO, list[OwnerDTO], list[TeamDTO], dict[int, list[MatchupDTO]], WeekStatus],
    ],
) -> FakeProvider:
    return FakeProvider(seed)


# ---------------------------------------------------------------------------
# AC-DB-01: After a sync, DB contains league, owners, teams, matchups, scores
# ---------------------------------------------------------------------------


def test_AC_DB_01_fresh_sync_populates_every_entity(session: Session) -> None:
    """A fresh sync writes league, owners, teams, matchups, scores, and VP for completed weeks."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    assert league.name == "VP League"
    assert summary.league_id == league.id
    assert summary.league_changed is True
    # Verify the legacy provider_config_ref marker "membership" is persisted.
    assert league.provider_config_ref == "membership"

    owners = list(session.scalars(select(Owner).where(Owner.league_id == league.id)).all())
    assert len(owners) == 4
    assert {o.external_id for o in owners} == {"owner-1", "owner-2", "owner-3", "owner-4"}

    teams = repo.get_teams(league.id, 2026)
    assert len(teams) == 4
    assert {t.external_id for t in teams} == {"team-1", "team-2", "team-3", "team-4"}
    # Each team is linked to its owner.
    owner_ids = {o.external_id: o.id for o in owners}
    team_owner_map = {t.external_id: t.owner_id for t in teams}
    assert team_owner_map["team-1"] == owner_ids["owner-1"]
    assert team_owner_map["team-4"] == owner_ids["owner-4"]

    # Four matchups per completed week, two completed weeks synced.
    matchups = list(session.scalars(select(Matchup)).all())
    assert len(matchups) == 4
    assert {m.week for m in matchups} == {1, 2}
    for m in matchups:
        assert m.is_complete is True
        assert m.is_playoff is False

    # Four scores per team per week: 4 teams * 2 weeks = 8 scores.
    scores = list(session.scalars(select(Score)).all())
    assert len(scores) == 8

    # VP was recomputed for both weeks.
    assert summary.weeks_synced == (1, 2)
    assert summary.weeks_with_vp_recomputed == (1, 2)

    # AC-DB-04: each score stores total VP and the four components.
    for score in scores:
        assert score.victory_points is not None
        assert score.vp_h2h is not None
        assert score.vp_top_half is not None
        assert score.vp_high is not None
        assert score.vp_low is not None
        # Total equals sum of components exactly (Decimal addition is exact).
        assert score.victory_points == (
            score.vp_h2h + score.vp_top_half + score.vp_high + score.vp_low
        )

    # Matchups and scores reference local integer team ids, never provider external ids.
    local_team_ids = {t.id for t in teams}
    for matchup in repo.get_week_matchups(league.id, 2026, 1):
        assert matchup.home_team_id in local_team_ids
        assert matchup.away_team_id in local_team_ids
    for score in repo.get_week_scores(league.id, 2026, 1):
        assert score.team_id in local_team_ids


# ---------------------------------------------------------------------------
# AC-DB-02: Idempotent repeat sync produces identical database contents
# ---------------------------------------------------------------------------


def test_AC_DB_02_idempotent_repeat_sync(session: Session) -> None:
    """Running the same sync twice produces identical rows and reports no changes on the second."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    first = service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    league_id_first = first.league_id
    count_rows_first = {
        "league": session.scalar(select(func.count()).select_from(League)),
        "owner": session.scalar(select(func.count()).select_from(Owner)),
        "team": session.scalar(select(func.count()).select_from(Team)),
        "matchup": session.scalar(select(func.count()).select_from(Matchup)),
        "score": session.scalar(select(func.count()).select_from(Score)),
    }
    scores_first = {
        (s.team_id, s.week): (
            s.points,
            s.victory_points,
            s.vp_h2h,
            s.vp_top_half,
            s.vp_high,
            s.vp_low,
        )
        for s in session.scalars(select(Score)).all()
    }

    second = service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    # No changes reported on the second sync.
    assert second.league_id == league_id_first
    assert second.league_changed is False
    assert second.owners_changed == 0
    assert second.teams_changed == 0
    assert second.weeks_with_vp_recomputed == ()

    # No duplicate rows.
    count_rows_second = {
        "league": session.scalar(select(func.count()).select_from(League)),
        "owner": session.scalar(select(func.count()).select_from(Owner)),
        "team": session.scalar(select(func.count()).select_from(Team)),
        "matchup": session.scalar(select(func.count()).select_from(Matchup)),
        "score": session.scalar(select(func.count()).select_from(Score)),
    }
    assert count_rows_first == count_rows_second

    # Score data (including VP) is byte-identical.
    scores_second = {
        (s.team_id, s.week): (
            s.points,
            s.victory_points,
            s.vp_h2h,
            s.vp_top_half,
            s.vp_high,
            s.vp_low,
        )
        for s in session.scalars(select(Score)).all()
    }
    assert scores_first == scores_second


# ---------------------------------------------------------------------------
# AC-DB-03: Score correction triggers full-week VP recompute for all teams
# ---------------------------------------------------------------------------


def test_AC_DB_09_recompute_stores_zero_h2h_on_cup_week(session: Session) -> None:
    """A stored cup week recomputes every team's H2H VP to zero and keeps other components."""
    SyncService(_build_provider(_basic_seed()), session).sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    league_season = repo.get_league_season(league.id, 2026)
    assert league_season is not None
    week1_before = {
        score.team_id: score.vp_h2h for score in repo.get_week_scores(league.id, 2026, 1)
    }
    league_season.cup_week = 1
    session.commit()

    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary.weeks_recomputed == (1, 2)
    week1_after = repo.get_week_scores(league.id, 2026, 1)
    week2_after = repo.get_week_scores(league.id, 2026, 2)
    assert all(score.vp_h2h == Decimal(0) for score in week1_after)
    # Week 2 is not the cup week and keeps its ordinary head-to-head VP.
    assert any(score.vp_h2h != Decimal(0) for score in week2_after)
    for score in week1_after:
        assert score.victory_points == (
            score.vp_h2h + score.vp_top_half + score.vp_high + score.vp_low
        )
    # Week 1 was not a bye week, so clearing the cup week restores its H2H values.
    assert any(value != Decimal(0) for value in week1_before.values())

    league_season.cup_week = None
    session.commit()
    SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    restored = {score.team_id: score.vp_h2h for score in repo.get_week_scores(league.id, 2026, 1)}
    assert restored == week1_before


def test_sync_honours_an_already_stored_cup_week(session: Session) -> None:
    """A sync that changes a cup-week score recomputes it with zero head-to-head VP."""
    provider = _build_provider(_basic_seed())
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    league_season = repo.get_league_season(league.id, 2026)
    assert league_season is not None
    league_season.cup_week = 2
    session.commit()

    corrected_seed = _basic_seed()
    week2 = corrected_seed[("league-1", 2026)][3][2]
    corrected_seed[("league-1", 2026)][3][2] = [
        MatchupDTO(
            week=2,
            home=MatchupSideDTO(
                team_external_id=week2[0].home.team_external_id,
                points=Decimal("131.00"),
            ),
            away=week2[0].away,
            is_playoff=week2[0].is_playoff,
            is_complete=week2[0].is_complete,
        ),
        *week2[1:],
    ]

    summary = SyncService(_build_provider(corrected_seed), session).sync_league(
        _league_ref(), "fake", 2026
    )
    session.commit()

    assert 2 in summary.weeks_with_vp_recomputed
    assert all(score.vp_h2h == Decimal(0) for score in repo.get_week_scores(league.id, 2026, 2))
    assert any(score.vp_h2h != Decimal(0) for score in repo.get_week_scores(league.id, 2026, 1))


def test_AC_DB_03_score_correction_recomputes_full_week(session: Session) -> None:
    """Changing one team's score causes VP to be recomputed for every team in that week."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    week1_scores_before = {
        s.team_id: (s.points, s.victory_points, s.vp_h2h, s.vp_top_half, s.vp_high, s.vp_low)
        for s in repo.get_week_scores(league.id, 2026, 1)
    }
    # Sanity: week 1 had four teams with distinct scores, so no H2H ties; highest got +1 high.
    assert len(week1_scores_before) == 4
    assert all(vals[1] is not None for vals in week1_scores_before.values())

    # Now mutate the provider so team-1's week-1 score changes dramatically.
    corrected_seed = _basic_seed()
    original_matchups = corrected_seed[("league-1", 2026)][3]
    new_week1 = []
    for m in original_matchups[1]:
        if m.week == 1 and m.home.team_external_id == "team-1":
            m = MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("80.00")),
                away=m.away,
                is_playoff=m.is_playoff,
                is_complete=m.is_complete,
            )
        new_week1.append(m)
    corrected_seed[("league-1", 2026)][3][1] = new_week1

    corrected_provider = _build_provider(corrected_seed)
    corrected_service = SyncService(corrected_provider, session)
    corrected_summary = corrected_service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    # The week with the correction was recomputed.
    assert 1 in corrected_summary.weeks_with_vp_recomputed
    # Week 2 was unchanged, so not recomputed.
    assert 2 not in corrected_summary.weeks_with_vp_recomputed

    # Week 1 scores for ALL teams were touched (team-1's points changed and the rest had
    # their VP recomputed based on new ranking).
    week1_scores_after = {
        s.team_id: (s.points, s.victory_points, s.vp_h2h, s.vp_top_half, s.vp_high, s.vp_low)
        for s in repo.get_week_scores(league.id, 2026, 1)
    }
    # AC-DB-03: the corrected week is re-ranked as a whole, so every team's total VP changes,
    # not only the corrected team's points.
    assert len(week1_scores_after) == 4
    for team_id, before in week1_scores_before.items():
        assert week1_scores_after[team_id][1] != before[1]
    team_one_id = next(t.id for t in repo.get_teams(league.id, 2026) if t.external_id == "team-1")
    assert week1_scores_after[team_one_id][0] == Decimal("80.00")

    # Week 2 was untouched.
    week2_scores_after = {
        s.team_id: (s.points, s.victory_points) for s in repo.get_week_scores(league.id, 2026, 2)
    }
    week2_scores_before = {
        s.team_id: (s.points, s.victory_points) for s in repo.get_week_scores(league.id, 2026, 2)
    }
    # We haven't changed week 2 data, so the persisted rows are identical.
    assert week2_scores_after == week2_scores_before


# ---------------------------------------------------------------------------
# Byes: teams with no opponent get rank components but no H2H component
# ---------------------------------------------------------------------------


def test_bye_weeks_keep_rank_components_and_survive_recompute(session: Session) -> None:
    """A bye team earns top-half/high/low but zero H2H, on both sync and provider-free recompute."""
    seed = _basic_seed(last_completed_week=3, include_bye=True, regular_season_length=3)
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()
    after_sync = _vp_rows(session)

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    teams = {t.external_id: t.id for t in repo.get_teams(league.id, 2026)}
    week_three = {s.team_id: s for s in repo.get_week_scores(league.id, 2026, 3)}
    # team-1 and team-4 had byes in week 3 (no away opponent): no H2H, rank components kept.
    assert week_three[teams["team-1"]].vp_h2h == Decimal("0.000000")
    assert week_three[teams["team-1"]].vp_high == Decimal("1.000000")
    assert week_three[teams["team-1"]].vp_top_half == Decimal("1.000000")
    assert week_three[teams["team-4"]].vp_h2h == Decimal("0.000000")
    assert week_three[teams["team-4"]].vp_low == Decimal("-1.000000")

    _zero_vp(session)
    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary.weeks_recomputed == (1, 2, 3)
    assert _vp_rows(session) == after_sync
    recomputed_week_three = {s.team_id: s for s in repo.get_week_scores(league.id, 2026, 3)}
    assert recomputed_week_three[teams["team-1"]].vp_h2h == Decimal("0.000000")
    assert recomputed_week_three[teams["team-1"]].vp_high == Decimal("1.000000")
    assert recomputed_week_three[teams["team-4"]].vp_low == Decimal("-1.000000")


# ---------------------------------------------------------------------------
# Incomplete/playoff weeks: VP stays at zero even though rows are stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed_kwargs",
    [
        pytest.param({"playoff_week": 3}, id="playoff"),
        pytest.param({"incomplete_week": 3}, id="incomplete"),
    ],
)
def test_non_scoring_weeks_store_rows_but_no_vp(
    session: Session, seed_kwargs: dict[str, int]
) -> None:
    """A playoff or incomplete week is stored with zero VP, even when explicitly requested."""
    seed = _basic_seed(last_completed_week=2, **seed_kwargs)
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", 2026, weeks=[1, 2, 3])
    session.commit()

    # All three weeks were synced; only the completed non-playoff weeks (1, 2) earned VP.
    assert summary.weeks_synced == (1, 2, 3)
    assert 3 not in summary.weeks_with_vp_recomputed

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    week3_scores = repo.get_week_scores(league.id, 2026, 3)
    # Score rows exist for every team in the week, with every VP column zero.
    assert len(week3_scores) == 4
    for score in week3_scores:
        assert score.victory_points == Decimal("0.000000")
        assert score.vp_h2h == Decimal("0.000000")
        assert score.vp_top_half == Decimal("0.000000")
        assert score.vp_high == Decimal("0.000000")
        assert score.vp_low == Decimal("0.000000")


# ---------------------------------------------------------------------------
# WeekStatus=None and explicit weeks
# ---------------------------------------------------------------------------


def test_week_status_none_with_no_explicit_weeks_upserts_only_metadata(
    session: Session,
) -> None:
    """When no week has completed and none were requested, only league/owners/teams are upserted."""
    seed = _basic_seed(last_completed_week=None)
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    # Metadata was persisted.
    assert summary.league_changed is True
    assert summary.owners_changed == 4
    assert summary.teams_changed == 4
    # No matchup or score rows were written.
    assert summary.weeks_synced == ()
    assert summary.weeks_with_vp_recomputed == ()
    assert session.scalar(select(func.count()).select_from(Matchup)) == 0
    assert session.scalar(select(func.count()).select_from(Score)) == 0


def test_explicit_weeks_synced_regardless_of_week_status(session: Session) -> None:
    """Explicit weeks are synced even when WeekStatus reports no completed weeks."""
    seed = _basic_seed(last_completed_week=None)
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", 2026, weeks=[1, 2])
    session.commit()

    # The two requested weeks were synced and, being complete, had VP recomputed.
    assert summary.weeks_synced == (1, 2)
    assert summary.weeks_with_vp_recomputed == (1, 2)
    assert session.scalar(select(func.count()).select_from(Matchup)) == 4
    assert session.scalar(select(func.count()).select_from(Score)) == 8


# ---------------------------------------------------------------------------
# Persistence-boundary quantization of exactly-tied high scores
# ---------------------------------------------------------------------------


def test_tied_high_score_persists_quantized_thirds(session: Session) -> None:
    """A three-way high-score tie stores each team's exact 1/3 high VP as Decimal("0.333333").

    The exact Fraction arithmetic and the +1/-1 conservation invariants are owned by
    test_vp_engine.py; this asserts only the six-place quantization the NUMERIC(10,6) schema
    requires at the persistence boundary.
    """
    league = LeagueDTO(external_id="tie-league", name="Tie League", metadata={})
    owners = [OwnerDTO(external_id=f"owner-{i}", display_name=f"Owner {i}") for i in range(1, 5)]
    teams = [
        TeamDTO(
            external_id=f"team-{i}",
            name=f"Team {i}",
            division="East",
            owner_external_id=f"owner-{i}",
        )
        for i in range(1, 5)
    ]
    # Three-way tie for highest at 100.00, lone low at 50.00.
    matchups = {
        1: [
            MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("100.00")),
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-3", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-4", points=Decimal("50.00")),
                is_playoff=False,
                is_complete=True,
            ),
        ]
    }
    week_status = WeekStatus(last_completed_week=1)
    provider = FakeProvider({("tie-league", 2026): (league, owners, teams, matchups, week_status)})
    service = SyncService(provider, session)
    service.sync_league(_league_ref("tie-league"), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    tie_league = repo.get_league("fake", "tie-league")
    assert tie_league is not None
    teams_rows = repo.get_teams(tie_league.id, 2026)
    ext_to_id = {t.external_id: t.id for t in teams_rows}

    # Fraction(1, 3) → Decimal("0.333333") with ROUND_HALF_EVEN at six places.
    scores = {s.team_id: s for s in repo.get_week_scores(tie_league.id, 2026, 1)}
    for team_ext in ("team-1", "team-2", "team-3"):
        assert scores[ext_to_id[team_ext]].vp_high == Decimal("0.333333")


def test_split_low_score_penalty_persists_negative_thirds(session: Session) -> None:
    """A three-way low-score tie persists each -1/3 penalty with its sign and 6dp quantization.

    The engine's exact -1/3 arithmetic is owned by test_vp_engine.py; this asserts that the
    persistence boundary keeps the negative sign and the six-place scale instead of storing zero.
    """
    league = LeagueDTO(external_id="low-tie", name="Low Tie", metadata={})
    owners = [OwnerDTO(external_id=f"owner-{i}", display_name=f"Owner {i}") for i in range(1, 5)]
    teams = [
        TeamDTO(
            external_id=f"team-{i}",
            name=f"Team {i}",
            division="East",
            owner_external_id=f"owner-{i}",
        )
        for i in range(1, 5)
    ]
    # One high scorer at 100.00; the other three tie for the lowest score at 10.00.
    matchups = {
        1: [
            MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("10.00")),
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=1,
                home=MatchupSideDTO(team_external_id="team-3", points=Decimal("10.00")),
                away=MatchupSideDTO(team_external_id="team-4", points=Decimal("10.00")),
                is_playoff=False,
                is_complete=True,
            ),
        ]
    }
    week_status = WeekStatus(last_completed_week=1)
    provider = FakeProvider({("low-tie", 2026): (league, owners, teams, matchups, week_status)})
    SyncService(provider, session).sync_league(_league_ref("low-tie"), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    low_tie_league = repo.get_league("fake", "low-tie")
    assert low_tie_league is not None
    ext_to_id = {t.external_id: t.id for t in repo.get_teams(low_tie_league.id, 2026)}
    scores = {s.team_id: s for s in repo.get_week_scores(low_tie_league.id, 2026, 1)}

    # Fraction(-1, 3) → Decimal("-0.333333"): the sign survives and the scale is exactly six.
    for team_ext in ("team-2", "team-3", "team-4"):
        low = scores[ext_to_id[team_ext]].vp_low
        assert low == Decimal("-0.333333")
        assert low < 0
        assert low.as_tuple().exponent == -6


# ---------------------------------------------------------------------------
# Transaction ownership: the caller commits or rolls back
# ---------------------------------------------------------------------------


def test_sync_leaves_the_transaction_to_the_caller(session: Session) -> None:
    """SyncService never commits, so a caller rollback discards every row the sync wrote."""
    provider = _build_provider(_basic_seed())
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)

    assert session.scalar(select(func.count()).select_from(Score)) == 8
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Score)) == 0


# ---------------------------------------------------------------------------
# AC-DB-07: Sync tests use fixtures only, never call live ESPN
# ---------------------------------------------------------------------------


# This property is structural: every test above uses FakeProvider and never imports or invokes
# the ESPN adapter. A boundary test in test_domain_boundaries.py / test_provider_abstraction.py
# enforces that no module outside providers/espn/ imports espn_api.


# ---------------------------------------------------------------------------
# Newly completed week triggers VP recompute
# ---------------------------------------------------------------------------


def test_newly_completed_week_triggers_vp_recompute(session: Session) -> None:
    """A week that flips from incomplete to complete has its VP recomputed on the next sync."""
    # First sync: week 1 is complete, week 2 is incomplete.
    seed = _basic_seed(last_completed_week=1, incomplete_week=2)
    provider = _build_provider(seed)
    service = SyncService(provider, session)
    first = service.sync_league(_league_ref(), "fake", 2026, weeks=[1, 2])
    session.commit()

    # Week 2 was incomplete so no VP was written.
    assert 2 not in first.weeks_with_vp_recomputed
    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    week2_before = {s.team_id: s.victory_points for s in repo.get_week_scores(league.id, 2026, 2)}
    assert all(vp == Decimal("0.000000") for vp in week2_before.values())

    # Second sync: now week 2 is complete.
    completed_seed = _basic_seed(last_completed_week=2)
    completed_provider = _build_provider(completed_seed)
    completed_service = SyncService(completed_provider, session)
    second = completed_service.sync_league(_league_ref(), "fake", 2026, weeks=[1, 2])
    session.commit()

    # Week 2 was newly completed (matchup is_complete flipped) → VP recomputed.
    assert 2 in second.weeks_with_vp_recomputed
    week2_after = {s.team_id: s.victory_points for s in repo.get_week_scores(league.id, 2026, 2)}
    # After recompute, the week-2 VP values differ from the prior zeros (the fixture scores
    # produce non-zero VP for some teams).
    assert week2_after != week2_before


# ---------------------------------------------------------------------------
# Provider-free recompute (CLI `recompute`): stored rows + the VP engine only
# ---------------------------------------------------------------------------


class _ExplodingProvider:
    """A provider that fails loudly if any of its methods is called.

    Binding it to a SyncService proves that recompute_league never reaches for the provider.
    """

    provider_id = "fake"

    def fetch_league(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("recompute must not call the provider")

    fetch_owners = fetch_league
    fetch_teams = fetch_league
    fetch_matchups = fetch_league
    current_week = fetch_league


def _vp_rows(session: Session, season: int = 2026) -> dict[tuple[int, int], tuple[Decimal, ...]]:
    """Snapshot (week, team_id) → points and VP columns for before/after comparisons."""
    return {
        (score.week, score.team_id): (
            score.points,
            score.victory_points,
            score.vp_h2h,
            score.vp_top_half,
            score.vp_high,
            score.vp_low,
        )
        for score in session.scalars(select(Score).where(Score.season == season)).all()
    }


def _zero_vp(session: Session) -> None:
    """Clear every stored VP value so a recompute has visible work to do."""
    for score in session.scalars(select(Score)).all():
        score.victory_points = Decimal("0")
        score.vp_h2h = Decimal("0")
        score.vp_top_half = Decimal("0")
        score.vp_high = Decimal("0")
        score.vp_low = Decimal("0")
    session.commit()


def test_recompute_rebuilds_vp_without_calling_the_provider(session: Session) -> None:
    """Recompute rebuilds stored weeks from persisted rows, never touching the provider."""
    provider = _build_provider(_basic_seed(regular_season_length=2))
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()
    after_sync = _vp_rows(session)

    # Corrupt every VP value, then prove recompute reconstructs it exactly. An exploding provider
    # is bound but must never be reached; then the same holds with no provider bound at all.
    _zero_vp(session)
    summary = SyncService(_ExplodingProvider(), session).recompute_league(
        _league_ref(), "fake", 2026
    )
    session.commit()

    assert summary.regular_season_length == 2
    assert summary.weeks_recomputed == (1, 2)
    assert summary.weeks_skipped == ()
    assert _vp_rows(session) == after_sync

    _zero_vp(session)
    provider_free = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert provider_free.weeks_recomputed == (1, 2)
    assert _vp_rows(session) == after_sync


def test_sync_without_a_provider_raises_sync_error(session: Session) -> None:
    """The provider-free service refuses to sync instead of raising AttributeError."""
    with pytest.raises(SyncError, match="requires a provider"):
        SyncService(None, session).sync_league(_league_ref(), "fake", 2026)


def test_recompute_unknown_league_raises_league_not_found(session: Session) -> None:
    """Recompute against a league that was never synced reports a structured error."""
    with pytest.raises(LeagueNotFoundError, match="not stored"):
        SyncService(None, session).recompute_league(_league_ref("ghost"), "fake", 2026)


def test_sync_unknown_league_raises_league_not_found(session: Session) -> None:
    """A provider that does not know the league season is translated into LeagueNotFoundError."""
    provider = _build_provider(_basic_seed())
    with pytest.raises(LeagueNotFoundError, match="no league"):
        SyncService(provider, session).sync_league(_league_ref("missing"), "fake", 2026)


def test_recompute_without_stored_regular_season_length_raises(session: Session) -> None:
    """Recompute refuses to guess the season shape when metadata has no regular-season length."""
    provider = _build_provider(_basic_seed(regular_season_length=None))
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()

    with pytest.raises(MissingRegularSeasonLengthError, match="regular_season_length"):
        SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)


def test_recompute_skips_incomplete_and_playoff_weeks(session: Session) -> None:
    """Stored incomplete/playoff weeks are skipped and keep zero VP (AC-ST-08)."""
    seed = _basic_seed(
        last_completed_week=2,
        incomplete_week=3,
        playoff_week=4,
        regular_season_length=4,
    )
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026, weeks=[1, 2, 3, 4])
    session.commit()

    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary.weeks_recomputed == (1, 2)
    assert summary.weeks_skipped == (3, 4)

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    for week in (3, 4):
        for score in repo.get_week_scores(league.id, 2026, week):
            assert score.victory_points == Decimal("0.000000")
            assert score.vp_h2h == Decimal("0.000000")
            assert score.vp_top_half == Decimal("0.000000")
            assert score.vp_high == Decimal("0.000000")
            assert score.vp_low == Decimal("0.000000")


def test_recompute_honors_the_stored_regular_season_length(session: Session) -> None:
    """Weeks stored beyond the regular season are never touched, even when complete."""
    seed = _basic_seed(regular_season_length=2)
    matchups = seed[("league-1", 2026)][3]
    for week in (3, 4):
        matchups[week] = [
            MatchupDTO(
                week=week,
                home=MatchupSideDTO(team_external_id="team-1", points=Decimal("120.00")),
                away=MatchupSideDTO(team_external_id="team-2", points=Decimal("100.00")),
                is_playoff=False,
                is_complete=True,
            ),
            MatchupDTO(
                week=week,
                home=MatchupSideDTO(team_external_id="team-3", points=Decimal("90.00")),
                away=MatchupSideDTO(team_external_id="team-4", points=Decimal("80.00")),
                is_playoff=False,
                is_complete=True,
            ),
        ]
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026, weeks=[1, 2, 3, 4])
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    # Sentinel VP on the two weeks outside the stored regular season.
    for week in (3, 4):
        for score in repo.get_week_scores(league.id, 2026, week):
            score.victory_points = Decimal("42.000000")
    session.commit()

    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary.regular_season_length == 2
    assert summary.weeks_recomputed == (1, 2)
    for week in (3, 4):
        for score in repo.get_week_scores(league.id, 2026, week):
            assert score.victory_points == Decimal("42.000000")


def test_recompute_skips_weeks_without_stored_matchups(session: Session) -> None:
    """Weeks in the regular season with no stored matchups are reported as skipped."""
    seed = _basic_seed(last_completed_week=1, regular_season_length=3)
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026, weeks=[1])
    session.commit()

    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)

    assert summary.weeks_recomputed == (1,)
    assert summary.weeks_skipped == (2, 3)


def test_recompute_preserves_bye_week_results(session: Session) -> None:
    """A bye week rebuilt by recompute matches what sync produced: no H2H, rank VP kept."""
    seed = _basic_seed(last_completed_week=3, include_bye=True, regular_season_length=3)
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()
    after_sync = _vp_rows(session)

    _zero_vp(session)
    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary.weeks_recomputed == (1, 2, 3)
    assert _vp_rows(session) == after_sync

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    teams = {t.external_id: t.id for t in repo.get_teams(league.id, 2026)}
    week3 = {s.team_id: s for s in repo.get_week_scores(league.id, 2026, 3)}
    # team-1 and team-4 had byes: no H2H, but the bye team keeps its high/low/top-half VP.
    assert week3[teams["team-1"]].vp_h2h == Decimal("0.000000")
    assert week3[teams["team-1"]].vp_high == Decimal("1.000000")
    assert week3[teams["team-4"]].vp_h2h == Decimal("0.000000")
    assert week3[teams["team-4"]].vp_low == Decimal("-1.000000")


# ---------------------------------------------------------------------------
# Per-season settings: sync writes the league_season row recompute reads
# ---------------------------------------------------------------------------


def test_sync_writes_the_provider_metadata_to_a_league_season_row(session: Session) -> None:
    """Sync stores the provider's per-season settings on the requested season's row."""
    seed = _basic_seed(regular_season_length=2)
    provider = _build_provider(seed)
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    season_row = repo.get_league_season(league.id, 2026)
    assert season_row is not None
    # The whole provider metadata round-trips onto the season row, including the length.
    assert season_row.league_season_metadata == seed[("league-1", 2026)][0].metadata
    assert season_row.league_season_metadata["regular_season_length"] == 2


def test_repeat_sync_keeps_the_league_season_row_idempotent(session: Session) -> None:
    """Re-running the same sync leaves one unchanged league_season row (AC-DB-02)."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)
    service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    first_row = repo.get_league_season(league.id, 2026)
    assert first_row is not None
    first = (first_row.id, dict(first_row.league_season_metadata))
    count_first = session.scalar(select(func.count()).select_from(LeagueSeason))

    service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    second_row = repo.get_league_season(league.id, 2026)
    assert second_row is not None
    assert (second_row.id, dict(second_row.league_season_metadata)) == first
    assert count_first == 1
    assert session.scalar(select(func.count()).select_from(LeagueSeason)) == 1


def test_recompute_uses_each_seasons_own_regular_season_length(session: Session) -> None:
    """Two seasons with different lengths each recompute against their own stored value.

    The league row is shared by both seasons and its metadata is overwritten by the newest sync
    (2026, length 2), so a league-level lookup would recompute 2025 with length 2. Reading the
    season row keeps 2025 at its own length 1: week 2 is stored and complete but outside that
    season's regular season, so it is not recomputed.
    """
    seed = {
        # 2025 has two stored, complete weeks but a one-week regular season.
        **_basic_seed(season=2025, regular_season_length=1, last_completed_week=2),
        **_basic_seed(season=2026, regular_season_length=2),
    }
    provider = _build_provider(seed)
    service = SyncService(provider, session)
    service.sync_league(_league_ref(), "fake", 2025)
    session.commit()
    service.sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    season_2025 = repo.get_league_season(league.id, 2025)
    season_2026 = repo.get_league_season(league.id, 2026)
    assert season_2025 is not None
    assert season_2026 is not None
    assert season_2025.league_season_metadata["regular_season_length"] == 1
    assert season_2026.league_season_metadata["regular_season_length"] == 2
    # Week 2 of 2025 really is stored and complete; only the season bound keeps it out.
    assert len(repo.get_week_matchups(league.id, 2025, 2)) == 2

    summary_2025 = SyncService(None, session).recompute_league(_league_ref(), "fake", 2025)
    session.commit()
    summary_2026 = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)
    session.commit()

    assert summary_2025.regular_season_length == 1
    assert summary_2025.weeks_recomputed == (1,)
    assert summary_2026.regular_season_length == 2
    assert summary_2026.weeks_recomputed == (1, 2)


def test_recompute_reads_the_season_row_not_the_league_row(session: Session) -> None:
    """Recompute uses the season row even when the league row has no usable length."""
    provider = _build_provider(_basic_seed(regular_season_length=2))
    SyncService(provider, session).sync_league(_league_ref(), "fake", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    # Strip the league-level value: recompute must not fall back to it.
    league.league_metadata = {}
    session.commit()

    summary = SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)

    assert summary.regular_season_length == 2
    assert summary.weeks_recomputed == (1, 2)


def test_recompute_without_a_league_season_row_raises(session: Session) -> None:
    """A stored league with no row for the requested season refuses to guess its shape."""
    repo = SyncRepository(session)
    league = repo.upsert_league(
        provider="fake",
        external_id="league-1",
        name="VP League",
        league_metadata={},
        provider_config_ref=PROVIDER_CONFIG_REF,
    ).row
    session.commit()
    assert repo.get_league_season(league.id, 2026) is None

    with pytest.raises(MissingRegularSeasonLengthError, match="league_season"):
        SyncService(None, session).recompute_league(_league_ref(), "fake", 2026)


def test_provider_display_text_is_normalized_before_persistence(session: Session) -> None:
    """Hostile provider names are stored as safe literal text, never escaped or truncated by DB."""
    seed = _basic_seed()
    league, owners, teams, matchups, week_status = seed[("league-1", 2026)]
    hostile_league = replace(
        league,
        name="\u202eE\u0301vil\x00<script>alert(1)</script>\n\t  League\u200b",
    )
    hostile_owners = [
        replace(owners[0], display_name="\x01Alice\u200d   Smith"),
        *owners[1:],
    ]
    hostile_teams = [
        replace(
            teams[0],
            name="<img src=x onerror=alert(1)>" + "x" * 10_000,
            division="East\x00West",
        ),
        *teams[1:],
    ]
    hostile_seed = {
        ("league-1", 2026): (
            hostile_league,
            hostile_owners,
            hostile_teams,
            matchups,
            week_status,
        )
    }

    SyncService(FakeProvider(hostile_seed), session).sync_league(_league_ref(), "fake", 2026)
    session.commit()
    session.expire_all()

    stored_league = session.scalar(select(League))
    assert stored_league is not None
    assert stored_league.name == "Évil<script>alert(1)</script> League"

    stored_owner = session.scalar(
        select(Owner).where(Owner.external_id == "owner-1", Owner.league_id == stored_league.id)
    )
    assert stored_owner is not None
    # The control character is stripped, whitespace collapses, and the ZWJ is preserved because
    # it is meaningful in emoji and some scripts.
    assert stored_owner.display_name == "Alice\u200d Smith"

    stored_team = session.scalar(
        select(Team).where(Team.external_id == "team-1", Team.season == 2026)
    )
    assert stored_team is not None
    assert stored_team.name.startswith("<img src=x onerror=alert(1)>")
    assert len(stored_team.name) == MAX_DISPLAY_TEXT_LENGTH
    assert stored_team.division == "EastWest"

    for stored_text in (stored_league.name, stored_owner.display_name, stored_team.name):
        assert "\x00" not in stored_text
        assert all(
            unicodedata.category(character) not in {"Cc", "Cs", "Zl", "Zp"}
            for character in stored_text
        )
        assert not any(
            character in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
            for character in stored_text
        )


def test_whitespace_only_division_is_stored_as_no_division(session: Session) -> None:
    """A division that normalizes away must not create an empty-named division group."""
    seed = _basic_seed()
    league, owners, teams, matchups, week_status = seed[("league-1", 2026)]
    teams_with_blank_division = [
        replace(teams[0], division="\x00   "),
        *teams[1:],
    ]
    blank_division_seed = {
        ("league-1", 2026): (league, owners, teams_with_blank_division, matchups, week_status)
    }

    SyncService(FakeProvider(blank_division_seed), session).sync_league(_league_ref(), "fake", 2026)
    session.commit()
    session.expire_all()

    stored_team = session.scalar(
        select(Team).where(Team.external_id == "team-1", Team.season == 2026)
    )
    assert stored_team is not None
    assert stored_team.division is None
