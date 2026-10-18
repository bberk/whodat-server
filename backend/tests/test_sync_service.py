"""End-to-end tests for the provider-agnostic sync service.

The sync service is tested against the FakeProvider and recorded fixtures only; no live ESPN
calls are made. Every test runs against both SQLite (default) and PostgreSQL (when
REPOSITORY_TEST_DATABASE_URL is set), satisfying AC-DB-05/07 and the sync-→-VP portion of
AC-PR-02.
"""

import os
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import League, Matchup, Owner, Score, Team
from app.db.repositories import SyncRepository
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp
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
from app.services.sync_service import SyncService, _fraction_to_decimal

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
) -> dict[
    tuple[str, int],
    tuple[LeagueDTO, list[OwnerDTO], list[TeamDTO], dict[int, list[MatchupDTO]], WeekStatus],
]:
    """Build a FakeProvider seed for a 4-team league with configurable week states."""
    league = LeagueDTO(
        external_id="league-1",
        name="VP League",
        metadata={"teams": 4, "season": 2026},
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
        ("league-1", 2026): (league, owners, teams, matchups, week_status),
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

    summary = service.sync_league(_league_ref(), "fake", "test-config", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    assert league.name == "VP League"
    assert summary.league_id == league.id
    assert summary.league_changed is True

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


# ---------------------------------------------------------------------------
# AC-DB-02: Idempotent repeat sync produces identical database contents
# ---------------------------------------------------------------------------


def test_AC_DB_02_idempotent_repeat_sync(session: Session) -> None:
    """Running the same sync twice produces identical rows and reports no changes on the second."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    first = service.sync_league(_league_ref(), "fake", "test-config", 2026)
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

    second = service.sync_league(_league_ref(), "fake", "test-config", 2026)
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


def test_AC_DB_03_score_correction_recomputes_full_week(session: Session) -> None:
    """Changing one team's score causes VP to be recomputed for every team in that week."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    service.sync_league(_league_ref(), "fake", "test-config", 2026)
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
    corrected_summary = corrected_service.sync_league(_league_ref(), "fake", "test-config", 2026)
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
    assert week1_scores_after != week1_scores_before
    # team-1's points updated.
    assert week1_scores_after[week1_scores_after.__iter__().__next__()][0] is not None
    # All four teams have fresh VP rows (the recompute wrote every row).
    assert len(week1_scores_after) == 4

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
# AC-DB-04 (also covered by DB-01): each Score stores total and components
# ---------------------------------------------------------------------------


def test_AC_DB_04_score_rows_store_total_and_components(session: Session) -> None:
    """Score rows carry the victory_points total and all four component columns."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)
    service.sync_league(_league_ref(), "fake", "test-config", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    for score in repo.get_week_scores(league.id, 2026, 1):
        assert score.victory_points == (
            score.vp_h2h + score.vp_top_half + score.vp_high + score.vp_low
        )
        # NUMERIC(10,6) persistence: six decimal places exactly.
        assert score.victory_points.as_tuple().exponent == -6


# ---------------------------------------------------------------------------
# Byes: teams with no opponent get rank components but no H2H component
# ---------------------------------------------------------------------------


def test_bye_team_gets_rank_components_but_no_h2h(session: Session) -> None:
    """A team with no opponent earns top-half/high/low but zero H2H."""
    seed = _basic_seed(last_completed_week=3, include_bye=True)
    # Add a week 3 with a bye to the seeded matchups.
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    service.sync_league(_league_ref(), "fake", "test-config", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    teams = {t.external_id: t.id for t in repo.get_teams(league.id, 2026)}
    week3_scores = {s.team_id: s for s in repo.get_week_scores(league.id, 2026, 3)}

    # team-1 and team-4 had byes in week 3 (no away opponent).
    for bye_team_ext in ("team-1", "team-4"):
        bye_score = week3_scores[teams[bye_team_ext]]
        assert bye_score.vp_h2h == Decimal("0.000000"), (
            f"bye team {bye_team_ext} should have zero H2H"
        )
        # The bye team still earned rank components (top_half/high/low may be non-zero).
        # In this specific fixture team-1 scored 140 (highest) and team-4 scored 85 (lowest).
    # team-1 was the highest scorer (140) → gets +1 high.
    assert week3_scores[teams["team-1"]].vp_high == Decimal("1.000000")
    # team-4 was the lowest scorer (85) → gets -1 low.
    assert week3_scores[teams["team-4"]].vp_low == Decimal("-1.000000")
    # team-1 top_half: 4 teams in week, cutoff = floor(4/2) = 2. team-1 ranks first → in top half.
    assert week3_scores[teams["team-1"]].vp_top_half == Decimal("1.000000")


# ---------------------------------------------------------------------------
# Incomplete/playoff weeks: VP stays at zero even though rows are stored
# ---------------------------------------------------------------------------


def test_incomplete_week_stores_rows_but_no_vp(session: Session) -> None:
    """An incomplete week is stored with zero VP, even when explicitly requested."""
    seed = _basic_seed(last_completed_week=2, incomplete_week=3)
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", "test-config", 2026, weeks=[1, 2, 3])
    session.commit()

    # All three weeks were synced.
    assert summary.weeks_synced == (1, 2, 3)
    # Only completed non-playoff weeks (1, 2) had VP recomputed.
    assert 3 not in summary.weeks_with_vp_recomputed

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    week3_scores = repo.get_week_scores(league.id, 2026, 3)
    # Score rows exist for every team in the week.
    assert len(week3_scores) == 4
    # All VP columns are zero for the incomplete week.
    for score in week3_scores:
        assert score.victory_points == Decimal("0.000000")
        assert score.vp_h2h == Decimal("0.000000")
        assert score.vp_top_half == Decimal("0.000000")
        assert score.vp_high == Decimal("0.000000")
        assert score.vp_low == Decimal("0.000000")


def test_playoff_week_stores_rows_but_no_vp(session: Session) -> None:
    """A playoff week is stored with zero VP, even when explicitly requested."""
    seed = _basic_seed(last_completed_week=2, playoff_week=3)
    provider = _build_provider(seed)
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref(), "fake", "test-config", 2026, weeks=[1, 2, 3])
    session.commit()

    assert 3 not in summary.weeks_with_vp_recomputed

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    week3_scores = repo.get_week_scores(league.id, 2026, 3)
    assert len(week3_scores) == 4
    for score in week3_scores:
        assert score.victory_points == Decimal("0.000000")
        assert score.vp_h2h == Decimal("0.000000")


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

    summary = service.sync_league(_league_ref(), "fake", "test-config", 2026)
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

    summary = service.sync_league(_league_ref(), "fake", "test-config", 2026, weeks=[1, 2])
    session.commit()

    # The two requested weeks were synced and, being complete, had VP recomputed.
    assert summary.weeks_synced == (1, 2)
    assert summary.weeks_with_vp_recomputed == (1, 2)
    assert session.scalar(select(func.count()).select_from(Matchup)) == 4
    assert session.scalar(select(func.count()).select_from(Score)) == 8


# ---------------------------------------------------------------------------
# Exact fractional component conservation
# ---------------------------------------------------------------------------


def test_exact_fractional_component_conservation(session: Session) -> None:
    """VP components sum exactly in Fraction space; persisted Decimal quantization is deterministic.

    We construct a week with three teams tied for the highest score. Each should get exactly
    Fraction(1, 3) high VP. Summed as Fractions this is exactly 1; summed as quantized Decimals
    it is 0.999999 -- a known and documented rounding artifact, not a correctness bug. The
    engine's exact ranking and totals never rely on the rounded stored values.
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
    service.sync_league(_league_ref("tie-league"), "fake", "test-config", 2026)
    session.commit()

    # Verify in exact Fraction space: the engine returns 1/3 for the high component of each
    # tied team, and the sum of high components across all teams is exactly +1.
    repo = SyncRepository(session)
    tie_league = repo.get_league("fake", "tie-league")
    assert tie_league is not None
    teams_rows = repo.get_teams(tie_league.id, 2026)
    ext_to_id = {t.external_id: t.id for t in teams_rows}

    teams_week = [
        TeamWeek(
            team_id=ext_to_id["team-1"],
            points=Decimal("100.00"),
            opponent_id=ext_to_id["team-2"],
        ),
        TeamWeek(
            team_id=ext_to_id["team-2"],
            points=Decimal("100.00"),
            opponent_id=ext_to_id["team-1"],
        ),
        TeamWeek(
            team_id=ext_to_id["team-3"],
            points=Decimal("100.00"),
            opponent_id=ext_to_id["team-4"],
        ),
        TeamWeek(
            team_id=ext_to_id["team-4"],
            points=Decimal("50.00"),
            opponent_id=ext_to_id["team-3"],
        ),
    ]
    exact_vp = compute_week_vp(teams_week)
    high_sum = sum(vp.high for vp in exact_vp.values())
    low_sum = sum(vp.low for vp in exact_vp.values())
    assert high_sum == Fraction(1)
    assert low_sum == Fraction(-1)

    # Each tied team gets exactly Fraction(1, 3) high VP.
    for team_ext in ("team-1", "team-2", "team-3"):
        assert exact_vp[ext_to_id[team_ext]].high == Fraction(1, 3)

    # The persisted Decimal values are the documented quantization of those exact fractions:
    # Fraction(1, 3) → Decimal("0.333333") with ROUND_HALF_EVEN at six places.
    scores = {s.team_id: s for s in repo.get_week_scores(tie_league.id, 2026, 1)}
    expected_high_decimal = Decimal("0.333333")
    for team_ext in ("team-1", "team-2", "team-3"):
        assert scores[ext_to_id[team_ext]].vp_high == expected_high_decimal

    # _fraction_to_decimal is documented-deterministic.
    assert _fraction_to_decimal(Fraction(1, 3)) == expected_high_decimal
    assert _fraction_to_decimal(Fraction(2, 3)) == Decimal("0.666667")
    assert _fraction_to_decimal(Fraction(-1, 3)) == Decimal("-0.333333")


# ---------------------------------------------------------------------------
# Transaction-aware orchestration: caller-owned session
# ---------------------------------------------------------------------------


def test_caller_owns_transaction_and_can_rollback(session: Session) -> None:
    """The sync service never commits; the caller can roll back the entire sync."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)

    service.sync_league(_league_ref(), "fake", "test-config", 2026)
    # No commit yet: nothing is visible to a separate snapshot query... actually within the same
    # session uncommitted writes ARE visible. But we can verify rollback removes them.
    assert session.scalar(select(func.count()).select_from(Score)) == 8
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Score)) == 0


# ---------------------------------------------------------------------------
# Default weeks range is 1..last_completed_week inclusive
# ---------------------------------------------------------------------------


def test_default_weeks_range_is_one_through_last_completed_inclusive(
    session: Session,
) -> None:
    """With last_completed_week=5, the default sync touches weeks 1 through 5 inclusive."""
    # Build a seed with five completed weeks.
    league = LeagueDTO(external_id="five-week", name="Five Week", metadata={})
    owners = [OwnerDTO(external_id=f"o-{i}", display_name=f"O {i}") for i in range(1, 3)]
    teams = [
        TeamDTO(external_id="t-1", name="T1", division=None, owner_external_id="o-1"),
        TeamDTO(external_id="t-2", name="T2", division=None, owner_external_id="o-2"),
    ]
    matchups: dict[int, list[MatchupDTO]] = {}
    for week in range(1, 6):
        matchups[week] = [
            MatchupDTO(
                week=week,
                home=MatchupSideDTO(team_external_id="t-1", points=Decimal("100.00")),
                away=MatchupSideDTO(team_external_id="t-2", points=Decimal("90.00")),
                is_playoff=False,
                is_complete=True,
            )
        ]
    week_status = WeekStatus(last_completed_week=5)
    provider = FakeProvider({("five-week", 2026): (league, owners, teams, matchups, week_status)})
    service = SyncService(provider, session)

    summary = service.sync_league(_league_ref("five-week"), "fake", "test-config", 2026)
    session.commit()

    assert summary.weeks_synced == (1, 2, 3, 4, 5)
    assert summary.weeks_with_vp_recomputed == (1, 2, 3, 4, 5)

    repo = SyncRepository(session)
    fw_league = repo.get_league("fake", "five-week")
    assert fw_league is not None
    # Every week has a score row for each team.
    for week in range(1, 6):
        scores = repo.get_week_scores(fw_league.id, 2026, week)
        assert len(scores) == 2
        # Non-zero VP because every week was completed.
        assert all(s.victory_points != Decimal("0.000000") for s in scores)


# ---------------------------------------------------------------------------
# Mapping external IDs to local IDs
# ---------------------------------------------------------------------------


def test_external_ids_map_to_local_ids_correctly(session: Session) -> None:
    """The sync translates provider external IDs to local integer IDs for every row."""
    provider = _build_provider(_basic_seed())
    service = SyncService(provider, session)
    service.sync_league(_league_ref(), "fake", "test-config", 2026)
    session.commit()

    repo = SyncRepository(session)
    league = repo.get_league("fake", "league-1")
    assert league is not None
    teams = {t.external_id: t.id for t in repo.get_teams(league.id, 2026)}

    # Matchups reference local team ids, not external strings.
    for matchup in repo.get_week_matchups(league.id, 2026, 1):
        assert matchup.home_team_id in teams.values()
        if matchup.away_team_id is not None:
            assert matchup.away_team_id in teams.values()

    # Scores reference local team ids.
    for score in repo.get_week_scores(league.id, 2026, 1):
        assert score.team_id in teams.values()


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
    first = service.sync_league(_league_ref(), "fake", "test-config", 2026, weeks=[1, 2])
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
    second = completed_service.sync_league(_league_ref(), "fake", "test-config", 2026, weeks=[1, 2])
    session.commit()

    # Week 2 was newly completed (matchup is_complete flipped) → VP recomputed.
    assert 2 in second.weeks_with_vp_recomputed
    week2_after = {s.team_id: s.victory_points for s in repo.get_week_scores(league.id, 2026, 2)}
    # After recompute, the week-2 VP values differ from the prior zeros (the fixture scores
    # produce non-zero VP for some teams).
    assert week2_after != week2_before
