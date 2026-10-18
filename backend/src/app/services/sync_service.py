"""Provider-agnostic sync service orchestrating league data ingestion and VP computation.

The sync service depends only on the LeagueProvider protocol and normalized DTOs, never on
ESPN-specific code. It orchestrates fetching, upserting, and VP computation using caller-owned
session transactions.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from sqlalchemy.orm import Session

from app.db.repositories import SyncRepository, WeeklyVPValues
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp
from app.providers.base import LeagueProvider, LeagueRef, MatchupDTO


@dataclass(frozen=True)
class SyncSummary:
    """Report what a sync_league call persisted and recomputed."""

    league_id: int
    season: int
    weeks_synced: tuple[int, ...]
    weeks_with_vp_recomputed: tuple[int, ...]
    league_changed: bool
    owners_changed: int
    teams_changed: int


# Quantization policy: NUMERIC(10,6) schema requires six decimal places.
# ROUND_HALF_EVEN is deterministic and matches IEEE 754 default rounding.
_VP_QUANT = Decimal("0.000001")


def _fraction_to_decimal(value: Fraction) -> Decimal:
    """Convert an exact Fraction to a Decimal quantized to six places with ROUND_HALF_EVEN.

    The conversion is deterministic: Fraction(1, 3) always becomes Decimal("0.333333").
    This quantization happens only at the persistence boundary; the engine never sees or
    uses these rounded values for ranking.
    """
    # Use numerator/denominator division to avoid str(Fraction) which produces "1/2" format.
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        _VP_QUANT, rounding=ROUND_HALF_EVEN
    )


class SyncService:
    """Orchestrate provider data ingestion, matchup/score upsert, and weekly VP recomputation.

    The service uses a caller-owned session and never commits or rolls back. Transaction
    ownership belongs to the caller, allowing the service to be embedded in larger workflows
    or tested with explicit commit/rollback control.
    """

    def __init__(self, provider: LeagueProvider, session: Session) -> None:
        """Bind the service to a provider and a caller-owned session."""
        self._provider = provider
        self._session = session
        self._repository = SyncRepository(session)

    def sync_league(
        self,
        league_ref: LeagueRef,
        provider_id: str,
        season: int,
        weeks: Sequence[int] | None = None,
    ) -> SyncSummary:
        """Fetch, upsert, and compute VP for a league season.

        When weeks is None, sync defaults to 1..last_completed_week. If last_completed_week
        is None and no explicit weeks were requested, only league/owners/teams are upserted
        and no matchup/score rows are created.

        When weeks is provided, those weeks are synced regardless of completion status.
        Incomplete or playoff weeks are stored with VP zero.

        For any week whose matchup/score data changed or is newly completed, VP is recomputed
        for every team in that week and persisted in the same transaction.
        """
        # Fetch and upsert league metadata.
        league_dto = self._provider.fetch_league(league_ref, season)
        league_result = self._repository.upsert_league(
            provider=provider_id,
            external_id=league_dto.external_id,
            name=league_dto.name,
            league_metadata=dict(league_dto.metadata),
            provider_config_ref=provider_id,
        )
        league_id = league_result.row.id
        league_changed = league_result.changed

        # Fetch and upsert owners, tracking their external_id → id mapping.
        owners_dto = self._provider.fetch_owners(league_ref, season)
        owner_external_to_id: dict[str, int] = {}
        owners_changed = 0
        for owner_dto in owners_dto:
            owner_result = self._repository.upsert_owner(
                league_id, owner_dto.external_id, owner_dto.display_name
            )
            owner_external_to_id[owner_dto.external_id] = owner_result.row.id
            if owner_result.changed:
                owners_changed += 1

        # Fetch and upsert teams, building external_id → id mapping.
        teams_dto = self._provider.fetch_teams(league_ref, season)
        team_external_to_id: dict[str, int] = {}
        teams_changed = 0
        for team_dto in teams_dto:
            owner_id = (
                owner_external_to_id[team_dto.owner_external_id]
                if team_dto.owner_external_id
                else None
            )
            team_result = self._repository.upsert_team(
                league_id,
                season,
                team_dto.external_id,
                team_dto.name,
                team_dto.division,
                owner_id,
            )
            team_external_to_id[team_dto.external_id] = team_result.row.id
            if team_result.changed:
                teams_changed += 1

        # Determine which weeks to sync.
        week_status = self._provider.current_week(league_ref, season)
        if weeks is None:
            if week_status.last_completed_week is None:
                # No completed weeks and no explicit request: only metadata, no matchups/scores.
                return SyncSummary(
                    league_id=league_id,
                    season=season,
                    weeks_synced=(),
                    weeks_with_vp_recomputed=(),
                    league_changed=league_changed,
                    owners_changed=owners_changed,
                    teams_changed=teams_changed,
                )
            weeks_to_sync = tuple(range(1, week_status.last_completed_week + 1))
        else:
            weeks_to_sync = tuple(weeks)

        # Sync each week: fetch matchups, upsert, and track changes.
        weeks_synced: list[int] = []
        weeks_needing_recompute: list[int] = []
        for week in weeks_to_sync:
            matchups_dto = self._provider.fetch_matchups(league_ref, season, week)
            week_changed = self._sync_week(
                league_id, season, week, matchups_dto, team_external_to_id
            )
            weeks_synced.append(week)
            if week_changed:
                weeks_needing_recompute.append(week)

        # Recompute VP for changed weeks.
        weeks_with_vp_recomputed: list[int] = []
        for week in weeks_needing_recompute:
            matchups = self._repository.get_week_matchups(league_id, season, week)
            if not matchups:
                continue
            # Determine if week is complete and not playoff.
            is_playoff = matchups[0].is_playoff
            is_complete = matchups[0].is_complete
            if is_playoff or not is_complete:
                # VP remains zero for incomplete or playoff weeks.
                continue
            self._recompute_week_vp(league_id, season, week)
            weeks_with_vp_recomputed.append(week)

        return SyncSummary(
            league_id=league_id,
            season=season,
            weeks_synced=tuple(weeks_synced),
            weeks_with_vp_recomputed=tuple(weeks_with_vp_recomputed),
            league_changed=league_changed,
            owners_changed=owners_changed,
            teams_changed=teams_changed,
        )

    def _sync_week(
        self,
        league_id: int,
        season: int,
        week: int,
        matchups_dto: Sequence[MatchupDTO],
        team_external_to_id: Mapping[str, int],
    ) -> bool:
        """Upsert matchups and scores for one week, returning whether anything changed."""
        changed = False
        for matchup_dto in matchups_dto:
            home_team_id = team_external_to_id[matchup_dto.home.team_external_id]
            away_team_id = (
                team_external_to_id[matchup_dto.away.team_external_id]
                if matchup_dto.away is not None
                else None
            )
            matchup_result = self._repository.upsert_matchup(
                league_id,
                season,
                week,
                home_team_id,
                away_team_id,
                matchup_dto.is_playoff,
                matchup_dto.is_complete,
            )
            if matchup_result.changed:
                changed = True

            # Upsert home team score.
            home_score_result = self._repository.upsert_score(
                home_team_id, league_id, season, week, matchup_dto.home.points
            )
            if home_score_result.changed:
                changed = True

            # Upsert away team score if present (not a bye).
            if matchup_dto.away is not None:
                away_team_id_int = team_external_to_id[matchup_dto.away.team_external_id]
                away_score_result = self._repository.upsert_score(
                    away_team_id_int, league_id, season, week, matchup_dto.away.points
                )
                if away_score_result.changed:
                    changed = True

        return changed

    def _recompute_week_vp(self, league_id: int, season: int, week: int) -> None:
        """Compute VP for a week and persist the results for all teams in that week."""
        matchups = self._repository.get_week_matchups(league_id, season, week)
        scores = self._repository.get_week_scores(league_id, season, week)

        # Build TeamWeek inputs: map each score to its opponent (if any).
        # Build a matchup lookup: team_id → opponent_id (or None for byes).
        team_to_opponent: dict[int, int | None] = {}
        for matchup in matchups:
            team_to_opponent[matchup.home_team_id] = matchup.away_team_id
            if matchup.away_team_id is not None:
                team_to_opponent[matchup.away_team_id] = matchup.home_team_id

        teams_week = [
            TeamWeek(
                team_id=score.team_id,
                points=score.points,
                opponent_id=team_to_opponent.get(score.team_id),
            )
            for score in scores
        ]

        # Compute exact VP using the pure engine.
        vp_by_team = compute_week_vp(teams_week)

        # Convert Fractions to Decimals at the persistence boundary.
        values_by_team: dict[int, WeeklyVPValues] = {
            team_id: WeeklyVPValues(
                victory_points=_fraction_to_decimal(vp.total),
                h2h=_fraction_to_decimal(vp.h2h),
                top_half=_fraction_to_decimal(vp.top_half),
                high=_fraction_to_decimal(vp.high),
                low=_fraction_to_decimal(vp.low),
            )
            for team_id, vp in vp_by_team.items()
        }

        # Persist all components in the same transaction.
        self._repository.persist_week_vp(league_id, season, week, values_by_team)
