"""Provider-agnostic sync service orchestrating league data ingestion and VP computation.

The sync service depends only on the LeagueProvider protocol and normalized DTOs, never on
ESPN-specific code. It orchestrates fetching, upserting, and VP computation using caller-owned
session transactions.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from sqlalchemy.orm import Session

from app.db.repositories import SyncRepository, WeeklyVPValues
from app.domain.types import TeamWeek
from app.domain.vp_engine import compute_week_vp
from app.providers.base import LeagueProvider, LeagueRef, MatchupDTO
from app.validation import normalize_display_text

#: Fixed non-secret value stored in ``league.provider_config_ref``. The column is a legacy pointer:
#: league credentials come from memberships, not from an environment-level bootstrap secret.
PROVIDER_CONFIG_REF = "membership"


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


@dataclass(frozen=True)
class RecomputeSummary:
    """Report the weeks a provider-free recompute_league call touched and skipped."""

    league_id: int
    season: int
    regular_season_length: int
    weeks_recomputed: tuple[int, ...]
    weeks_skipped: tuple[int, ...]


class SyncError(Exception):
    """Base class for recoverable sync and recompute failures reported by the CLI."""


class LeagueNotFoundError(SyncError):
    """Raised when a league is unknown to the provider or is not stored locally."""


class MissingRegularSeasonLengthError(SyncError):
    """Raised when a stored league season has no usable regular-season length.

    The length is read from that season's ``league_season`` row; a missing row or a row whose
    metadata lacks an integer, positive ``regular_season_length`` makes a season-shaped
    recompute impossible, so the CLI reports the error instead of guessing a week range.
    """


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


def _regular_season_length(metadata: Mapping[str, object]) -> int | None:
    """Return the stored regular-season length, or None when it is absent or unusable.

    The length is per season: each provider writes it into the ``league_season`` row's metadata
    for the season being synced (the ESPN adapter writes ``regular_season_length`` from
    ``settings.reg_season_count``). Booleans are rejected even though ``bool`` is an ``int``
    subclass, and non-positive values are treated as missing.
    """
    value = metadata.get("regular_season_length")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


class SyncService:
    """Orchestrate provider data ingestion, matchup/score upsert, and weekly VP recomputation.

    The service uses a caller-owned session and never commits or rolls back. Transaction
    ownership belongs to the caller, allowing the service to be embedded in larger workflows
    or tested with explicit commit/rollback control.

    A provider is required for :meth:`sync_league` and unused by :meth:`recompute_league`, which
    works entirely from persisted rows. Pass ``None`` to build a service that can only recompute.
    """

    def __init__(
        self,
        provider: LeagueProvider | None,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind the service to an optional provider, session, and clock."""
        self._provider = provider
        self._session = session
        self._clock = clock or (lambda: datetime.now(UTC))
        self._repository = SyncRepository(session)

    def _require_provider(self) -> LeagueProvider:
        """Return the bound provider, raising SyncError when the service has none."""
        if self._provider is None:
            raise SyncError("sync requires a provider; this service only supports recompute")
        return self._provider

    def sync_league(
        self,
        league_ref: LeagueRef,
        provider_id: str,
        season: int,
        weeks: Sequence[int] | None = None,
    ) -> SyncSummary:
        """Fetch, upsert, and compute VP for a league season.

        The league's ``provider_config_ref`` is the fixed non-secret value
        :data:`PROVIDER_CONFIG_REF` (``"membership"``), a legacy pointer recording that league
        credentials come from memberships rather than from an environment-level bootstrap.
        ESPN cookies are never written to DTOs or the database.

        The provider's per-season settings (``LeagueDTO.metadata``: regular season length, team
        count, scoring type, ...) are written to this season's ``league_season`` row, so a league's
        seasons stay independent and refreshing one season never overwrites another's settings.

        When weeks is None and the provider supplies a regular-season length, sync ingests the
        full regular-season schedule (including future incomplete matchups). Without that
        metadata it falls back to 1..last_completed_week rather than guessing a season shape.

        When weeks is provided, those weeks are synced regardless of completion status.
        Incomplete weeks are reconciled against the provider and receive no VP. Future sides
        with no provider points have no score row; zero-looking future scores are not results.

        A successful sync records the season's ``last_refreshed_at`` instant, so the admin seasons
        table can show when the provider data was last brought up to date. Only a provider-backed
        sync writes that value; provider-free recomputes and cup-week edits leave it untouched.

        For any week whose matchup/score data changed or is newly completed, VP is recomputed
        for every team in that week and persisted in the same transaction.

        Raises LeagueNotFoundError when the provider does not know the league season.
        """
        provider = self._require_provider()

        # Fetch the league, then upsert its league row and this season's row.
        try:
            league_dto = provider.fetch_league(league_ref, season)
        except KeyError as exc:
            raise LeagueNotFoundError(
                f"provider {provider_id!r} has no league {league_ref.external_id!r} "
                f"for season {season}"
            ) from exc
        league_result = self._repository.upsert_league(
            provider=provider_id,
            external_id=league_dto.external_id,
            # Provider display text is untrusted: normalize control/format characters, collapse
            # whitespace, and cap length before it reaches a text column. HTML stays literal.
            name=normalize_display_text(league_dto.name),
            league_metadata=dict(league_dto.metadata),
            provider_config_ref=PROVIDER_CONFIG_REF,
        )
        league_id = league_result.row.id
        league_changed = league_result.changed

        # Persist the provider's per-season settings for the requested season. They live on the
        # league_season row (one per season) so that syncing one season never overwrites another
        # season's regular-season length or scoring settings.
        self._repository.upsert_league_season(league_id, season, dict(league_dto.metadata))

        # Fetch and upsert owners, tracking their external_id → id mapping.
        owners_dto = provider.fetch_owners(league_ref, season)
        owner_external_to_id: dict[str, int] = {}
        owners_changed = 0
        for owner_dto in owners_dto:
            owner_result = self._repository.upsert_owner(
                league_id,
                owner_dto.external_id,
                normalize_display_text(owner_dto.display_name),
            )
            owner_external_to_id[owner_dto.external_id] = owner_result.row.id
            if owner_result.changed:
                owners_changed += 1

        # Fetch and upsert teams, building external_id → id mapping.
        teams_dto = provider.fetch_teams(league_ref, season)
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
                normalize_display_text(team_dto.name),
                # A division that normalizes to empty (whitespace/NUL only) means no division,
                # not a group with an empty name.
                normalize_display_text(team_dto.division or "") or None,
                owner_id,
            )
            team_external_to_id[team_dto.external_id] = team_result.row.id
            if team_result.changed:
                teams_changed += 1

        # Determine which weeks to sync. A known season length means the full schedule is in
        # scope, not just completed weeks; future pairings are required by the clinch calculator.
        week_status = provider.current_week(league_ref, season)
        regular_season_length = _regular_season_length(league_dto.metadata)
        if weeks is None:
            if regular_season_length is not None:
                weeks_to_sync = tuple(range(1, regular_season_length + 1))
            elif week_status.last_completed_week is None:
                weeks_to_sync = ()
            else:
                weeks_to_sync = tuple(range(1, week_status.last_completed_week + 1))
        else:
            weeks_to_sync = tuple(weeks)

        # Sync each week: fetch matchups, upsert, and track changes.
        weeks_synced: list[int] = []
        weeks_needing_recompute: list[int] = []
        for week in weeks_to_sync:
            matchups_dto = provider.fetch_matchups(league_ref, season, week)
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
            # A week earns VP only when every matchup is final and none is a playoff game.
            # A partially complete week is the normal mid-week state, so judging the week by
            # one matchup would compute VP from an unfinished schedule.
            if any(matchup.is_playoff or not matchup.is_complete for matchup in matchups):
                # VP remains zero for incomplete, mixed, or playoff weeks.
                continue
            self._recompute_week_vp(league_id, season, week)
            weeks_with_vp_recomputed.append(week)

        self._repository.set_league_season_last_refreshed(league_id, season, self._clock())
        return SyncSummary(
            league_id=league_id,
            season=season,
            weeks_synced=tuple(weeks_synced),
            weeks_with_vp_recomputed=tuple(weeks_with_vp_recomputed),
            league_changed=league_changed,
            owners_changed=owners_changed,
            teams_changed=teams_changed,
        )

    def recompute_league(
        self,
        league_ref: LeagueRef,
        provider_id: str,
        season: int,
    ) -> RecomputeSummary:
        """Recompute VP for a stored league season using only persisted data.

        This operation never calls the provider: it locates the league by its stored natural key
        (provider_id, external id) and reads the season's regular-season length from that season's
        stored ``league_season`` row, which every provider writes on sync. It then recomputes VP
        for every stored, complete, non-playoff week in that range with the pure engine and the
        existing repository. Weeks with no stored matchups, incomplete weeks, and playoff weeks
        are skipped and keep whatever VP sync stored for them (normally zero).

        Because sync only writes VP for weeks whose data changed, this is the operation to run
        after a scoring-rule change or to rebuild VP for every stored week in one pass.

        Raises LeagueNotFoundError when no league is stored for the natural key, and
        MissingRegularSeasonLengthError when the requested season has no ``league_season`` row or
        its stored metadata has no usable length.
        """
        league = self._repository.get_league(provider_id, league_ref.external_id)
        if league is None:
            raise LeagueNotFoundError(
                f"league {league_ref.external_id!r} for provider {provider_id!r} is not stored"
            )

        league_season = self._repository.get_league_season(league.id, season)
        if league_season is None:
            raise MissingRegularSeasonLengthError(
                f"league {league_ref.external_id!r} season {season} has no stored league_season row"
            )

        regular_season_length = _regular_season_length(league_season.league_season_metadata)
        if regular_season_length is None:
            raise MissingRegularSeasonLengthError(
                f"league {league_ref.external_id!r} season {season} has no usable "
                "regular_season_length in its stored league-season metadata"
            )

        weeks_recomputed: list[int] = []
        weeks_skipped: list[int] = []
        for week in range(1, regular_season_length + 1):
            matchups = self._repository.get_week_matchups(league.id, season, week)
            if not matchups:
                weeks_skipped.append(week)
                continue
            if any(matchup.is_playoff or not matchup.is_complete for matchup in matchups):
                # Playoff, incomplete, and mixed-completion weeks earn no VP, so leave their
                # stored values untouched.
                weeks_skipped.append(week)
                continue
            self._recompute_week_vp(league.id, season, week)
            weeks_recomputed.append(week)

        return RecomputeSummary(
            league_id=league.id,
            season=season,
            regular_season_length=regular_season_length,
            weeks_recomputed=tuple(weeks_recomputed),
            weeks_skipped=tuple(weeks_skipped),
        )

    def _sync_week(
        self,
        league_id: int,
        season: int,
        week: int,
        matchups_dto: Sequence[MatchupDTO],
        team_external_to_id: Mapping[str, int],
    ) -> bool:
        """Sync one week, reconciling only while its schedule is still incomplete.

        An incomplete week is a provider snapshot, not an append-only feed: stale pairings and
        scores are removed before current rows are upserted. A week with any incomplete matchup is
        reconciled and has its VP columns reset to zero, so a mixed-completion week never keeps
        stored VP. A completed week keeps the existing immutable-schedule behavior, including the
        separate ability to correct reported scores.
        """
        resolved = [
            (
                matchup_dto,
                team_external_to_id[matchup_dto.home.team_external_id],
                (
                    team_external_to_id[matchup_dto.away.team_external_id]
                    if matchup_dto.away is not None
                    else None
                ),
            )
            for matchup_dto in matchups_dto
        ]
        stored_matchups = self._repository.get_week_matchups(league_id, season, week)
        reconcile = (
            not resolved
            or any(not matchup.is_complete for matchup, _, _ in resolved)
            or any(not matchup.is_complete for matchup in stored_matchups)
        )
        completed_schedule = bool(stored_matchups) and not reconcile
        changed = False

        if reconcile:
            desired_home_ids = {home_team_id for _, home_team_id, _ in resolved}
            for stored_matchup in stored_matchups:
                if stored_matchup.home_team_id not in desired_home_ids:
                    self._repository.delete_matchup(stored_matchup)
                    changed = True

            desired_points = {
                home_team_id: matchup.home.points for matchup, home_team_id, _ in resolved
            }
            desired_points.update(
                {
                    away_team_id: matchup.away.points
                    for matchup, _, away_team_id in resolved
                    if away_team_id is not None and matchup.away is not None
                }
            )
            for stored_score in self._repository.get_week_scores(league_id, season, week):
                if desired_points.get(stored_score.team_id) is None:
                    self._repository.delete_score(stored_score)
                    changed = True

        for matchup_dto, home_team_id, away_team_id in resolved:
            if not completed_schedule:
                matchup_result = self._repository.upsert_matchup(
                    league_id,
                    season,
                    week,
                    home_team_id,
                    away_team_id,
                    matchup_dto.is_playoff,
                    matchup_dto.is_complete,
                )
                changed = changed or matchup_result.changed

            if matchup_dto.home.points is not None:
                home_score_result = self._repository.upsert_score(
                    home_team_id, league_id, season, week, matchup_dto.home.points
                )
                changed = changed or home_score_result.changed

            if (
                away_team_id is not None
                and matchup_dto.away is not None
                and matchup_dto.away.points is not None
            ):
                away_score_result = self._repository.upsert_score(
                    away_team_id, league_id, season, week, matchup_dto.away.points
                )
                changed = changed or away_score_result.changed

        if reconcile:
            scores = self._repository.get_week_scores(league_id, season, week)
            zero = WeeklyVPValues(
                victory_points=Decimal(0),
                h2h=Decimal(0),
                top_half=Decimal(0),
                high=Decimal(0),
                low=Decimal(0),
            )
            if any(
                score.victory_points != 0
                or score.vp_h2h != 0
                or score.vp_top_half != 0
                or score.vp_high != 0
                or score.vp_low != 0
                for score in scores
            ):
                changed = True
            self._repository.persist_week_vp(
                league_id, season, week, {score.team_id: zero for score in scores}
            )

        return changed

    def _recompute_week_vp(self, league_id: int, season: int, week: int) -> None:
        """Compute VP for a week and persist the results for all teams in that week.

        The season's stored ``cup_week`` decides scoring: on that week every team's head-to-head
        component is zero while the other components are unchanged. A missing league-season row has
        no cup week.
        """
        matchups = self._repository.get_week_matchups(league_id, season, week)
        scores = self._repository.get_week_scores(league_id, season, week)
        league_season = self._repository.get_league_season(league_id, season)
        is_cup_week = league_season is not None and league_season.cup_week == week

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
        vp_by_team = compute_week_vp(teams_week, h2h=not is_cup_week)

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
