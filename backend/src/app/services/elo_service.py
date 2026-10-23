"""Read-only Elo history and per-league Elo settings.

The service loads a league's stored seasons, teams, matchups, scores, and owner names in a small
number of queries, groups them into the pure domain inputs in :mod:`app.domain.elo`, and decorates
the domain result with display names and owners. History is always derived from stored rows; there
is no snapshot table, so adding, deleting, or correcting a season is reflected on the next read.

The service is transaction-neutral for reads. ``update_config`` flushes the settings row and the
caller (the route) owns the commit. Authorization for settings is enforced here as well as by the
route's dependencies: a non-member raises ``NotAMemberError`` (404 at the edge) and a member
without the global admin role raises ``AdminRequiredError`` (403).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.auth_repositories import MembershipRepository
from app.db.models import ROLE_ADMIN, League, LeagueSeason, Matchup, Owner, Score, Team
from app.db.repositories import SyncRepository
from app.domain.elo import (
    EloConfig,
    EloMatch,
    EloMode,
    EloSeasonRating,
    EloTeamHistory,
    EloWeek,
    EloWeekPoint,
    EloWeekReference,
    SeasonBoundary,
    SeasonInfo,
    compute_elo_history,
)
from app.services.league_service import AdminRequiredError, LeagueUser, NotAMemberError


class EloLeagueNotFoundError(LookupError):
    """Raised when no league is stored for a requested id."""

    def __init__(self, league_id: int) -> None:
        self.league_id = league_id
        super().__init__(f"League {league_id} is not stored")


class InvalidEloConfigError(ValueError):
    """Raised when Elo settings are outside the documented ranges."""


@dataclass(frozen=True)
class EloUnratedTeam:
    """A team with no rated week, listed separately from the chart and table."""

    team_key: str
    name: str
    reason: str


@dataclass(frozen=True)
class EloWarning:
    """A stored-data problem that skipped part of the history instead of failing the request."""

    season: int
    code: str
    message: str


@dataclass(frozen=True)
class EloTeamView:
    """One franchise's domain history plus its latest stored display identity."""

    team_key: str
    team_id: int
    name: str
    owner_name: str | None
    aliases: tuple[str, ...]
    history: EloTeamHistory


@dataclass(frozen=True)
class EloHistoryView:
    """The complete service result for one league and mode."""

    league_id: int
    mode: EloMode
    config: EloConfig
    seasons: tuple[int, ...]
    weeks: tuple[EloWeekPoint, ...]
    season_boundaries: tuple[SeasonBoundary, ...]
    teams: tuple[EloTeamView, ...]
    unrated_teams: tuple[EloUnratedTeam, ...]
    warnings: tuple[EloWarning, ...]


@dataclass(frozen=True)
class _TeamIdentity:
    """The latest stored name/owner/id and older names for one franchise slot."""

    team_key: str
    team_id: int
    name: str
    owner_name: str | None
    aliases: tuple[str, ...]
    first_season: int


def _team_key(provider: str, external_id: str) -> str:
    """Return a stable franchise key; the database team id changes every season."""
    return f"{provider}:{external_id}"


def _regular_season_length(row: LeagueSeason) -> int | None:
    """Read a usable regular-season length, or None when the stored metadata is invalid."""
    raw: object = row.league_season_metadata.get("regular_season_length")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return None
    return raw


def _group_matchups(rows: Iterable[Matchup]) -> dict[tuple[int, int], list[Matchup]]:
    """Group matchups by ``(season, week)`` while preserving repository order."""
    grouped: dict[tuple[int, int], list[Matchup]] = {}
    for row in rows:
        grouped.setdefault((row.season, row.week), []).append(row)
    return grouped


def _group_scores(rows: Iterable[Score]) -> dict[tuple[int, int], list[Score]]:
    """Group scores by ``(season, week)`` while preserving repository order."""
    grouped: dict[tuple[int, int], list[Score]] = {}
    for row in rows:
        grouped.setdefault((row.season, row.week), []).append(row)
    return grouped


class EloService:
    """Build Elo history from stored league data and manage its per-league settings."""

    def __init__(self, session: Session) -> None:
        """Bind the service to a caller-owned session."""
        self._session = session
        self._repository = SyncRepository(session)
        self._memberships = MembershipRepository(session)

    def commit(self) -> None:
        """Commit a settings mutation; read methods never commit."""
        self._session.commit()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_config(self, user: LeagueUser, league_id: int) -> EloConfig:
        """Return the league's saved settings, or the documented defaults when no row exists.

        Admin-only: a non-member receives the same 404 the league routes use, and a member without
        the global admin role receives 403.
        """
        self._require_admin_member(user, league_id)
        return self._settings(league_id)

    def update_config(
        self,
        user: LeagueUser,
        league_id: int,
        *,
        starting_rating: Decimal,
        k_factor: Decimal,
        margin_weight: Decimal,
        margin_cap: Decimal,
        season_regression: Decimal,
    ) -> EloConfig:
        """Validate and persist settings for an admin member, returning the saved values."""
        self._require_admin_member(user, league_id)
        try:
            config = EloConfig(
                starting_rating=starting_rating,
                k_factor=k_factor,
                margin_weight=margin_weight,
                margin_cap=margin_cap,
                season_regression=season_regression,
            )
        except ValueError as error:
            raise InvalidEloConfigError(str(error)) from None
        self._repository.upsert_elo_config(
            league_id,
            starting_rating=config.starting_rating,
            k_factor=config.k_factor,
            margin_weight=config.margin_weight,
            margin_cap=config.margin_cap,
            season_regression=config.season_regression,
        )
        return config

    def _require_admin_member(self, user: LeagueUser, league_id: int) -> None:
        """Enforce membership first (404) and then the global admin role (403)."""
        if self._memberships.get(user.user_id, league_id) is None:
            raise NotAMemberError("caller is not a member of this league")
        if user.role != ROLE_ADMIN:
            raise AdminRequiredError("only an admin may administer this league")

    def _settings(self, league_id: int) -> EloConfig:
        """Translate the stored row (or its absence) into validated domain settings."""
        row = self._repository.get_elo_config(league_id)
        if row is None:
            return EloConfig()
        return EloConfig(
            starting_rating=row.starting_rating,
            k_factor=row.k_factor,
            margin_weight=row.margin_weight,
            margin_cap=row.margin_cap,
            season_regression=row.season_regression,
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self, league_id: int, mode: EloMode) -> EloHistoryView:
        """Return full Elo history for a league in the requested mode.

        Unknown leagues raise :class:`EloLeagueNotFoundError`. A league with no stored seasons,
        teams, or rated weeks returns an empty history rather than an error, so the page can show
        its empty state. Invalid per-season metadata and missing scores skip only the affected
        data and add warnings; they never fail the whole history.
        """
        league = self._session.get(League, league_id)
        if league is None:
            raise EloLeagueNotFoundError(league_id)

        config = self._settings(league_id)
        season_rows = self._repository.list_league_seasons(league_id)
        team_rows = self._repository.list_teams(league_id)
        if not season_rows or not team_rows:
            return self._empty(league_id, mode, config, ())

        owner_names = self._owner_names(league_id)
        teams_by_season: dict[int, list[Team]] = {}
        teams_by_key: dict[str, list[Team]] = {}
        identities: dict[str, _TeamIdentity] = {}
        for team in team_rows:
            teams_by_season.setdefault(team.season, []).append(team)
            key = _team_key(league.provider, team.external_id)
            teams_by_key.setdefault(key, []).append(team)

        for key, rows in teams_by_key.items():
            identities[key] = self._identity(key, rows, owner_names)

        matchups_by_week = _group_matchups(self._repository.list_matchups(league_id))
        scores_by_week = _group_scores(self._repository.list_scores(league_id))

        warnings: list[EloWarning] = []
        season_infos: list[SeasonInfo] = []
        domain_weeks: list[EloWeek] = []
        valid_seasons: list[int] = []

        for season_row in season_rows:
            season = season_row.season
            regular_season_length = _regular_season_length(season_row)
            if regular_season_length is None:
                warnings.append(
                    EloWarning(
                        season=season,
                        code="missing_regular_season_length",
                        message=(
                            f"Season {season} has no usable regular-season length and was skipped."
                        ),
                    )
                )
                continue

            season_teams = teams_by_season.get(season, [])
            if not season_teams:
                warnings.append(
                    EloWarning(
                        season=season,
                        code="no_teams",
                        message=f"Season {season} has no stored teams and was skipped.",
                    )
                )
                continue

            team_key_by_id = {
                team.id: _team_key(league.provider, team.external_id) for team in season_teams
            }
            roster_keys = tuple(sorted(team_key_by_id.values()))
            season_infos.append(SeasonInfo(season=season, team_keys=roster_keys))
            valid_seasons.append(season)

            completed_weeks = self._completed_weeks(season, regular_season_length, matchups_by_week)
            for week in completed_weeks:
                league_week = self._league_week(
                    season=season,
                    week=week,
                    cup_week=season_row.cup_week,
                    matchups=matchups_by_week.get((season, week), []),
                    scores=scores_by_week.get((season, week), []),
                    team_key_by_id=team_key_by_id,
                    mode=mode,
                )
                if league_week.warning is not None:
                    warnings.append(
                        EloWarning(
                            season=season,
                            code="missing_score",
                            message=league_week.warning,
                        )
                    )
                domain_weeks.append(league_week.week)

        if not season_infos:
            return self._empty(league_id, mode, config, valid_seasons, warnings)

        history = compute_elo_history(domain_weeks, season_infos, config, mode=mode)

        team_views = tuple(
            EloTeamView(
                team_key=team.team_key,
                team_id=identities[team.team_key].team_id,
                name=identities[team.team_key].name,
                owner_name=identities[team.team_key].owner_name,
                aliases=identities[team.team_key].aliases,
                history=team,
            )
            for team in history.teams
            if team.team_key in identities
        )

        unrated_views: list[EloUnratedTeam] = []
        reported: set[str] = set()
        for key in history.unrated_teams:
            identity = identities.get(key)
            if identity is None:
                continue
            reported.add(key)
            unrated_views.append(
                EloUnratedTeam(
                    team_key=key,
                    name=identity.name,
                    reason="No rated matchups yet",
                )
            )
        for key, identity in sorted(
            identities.items(), key=lambda item: (item[1].first_season, item[0])
        ):
            if key not in reported and key not in {team.team_key for team in history.teams}:
                unrated_views.append(
                    EloUnratedTeam(
                        team_key=key,
                        name=identity.name,
                        reason="No rated matchups yet",
                    )
                )

        warnings.sort(key=lambda warning: (warning.season, warning.code, warning.message))
        return EloHistoryView(
            league_id=league_id,
            mode=mode,
            config=config,
            seasons=tuple(sorted(set(valid_seasons))),
            weeks=history.weeks,
            season_boundaries=history.season_boundaries,
            teams=team_views,
            unrated_teams=tuple(unrated_views),
            warnings=tuple(warnings),
        )

    def _empty(
        self,
        league_id: int,
        mode: EloMode,
        config: EloConfig,
        seasons: Sequence[int],
        warnings: Sequence[EloWarning] = (),
    ) -> EloHistoryView:
        """Return the documented empty history shape (200, not an error)."""
        return EloHistoryView(
            league_id=league_id,
            mode=mode,
            config=config,
            seasons=tuple(sorted(seasons)),
            weeks=(),
            season_boundaries=(),
            teams=(),
            unrated_teams=(),
            warnings=tuple(warnings),
        )

    def _owner_names(self, league_id: int) -> Mapping[int, str]:
        """Return stored owner display names keyed by owner id."""
        owners = self._session.scalars(select(Owner).where(Owner.league_id == league_id)).all()
        return {owner.id: owner.display_name for owner in owners}

    @staticmethod
    def _identity(
        team_key: str,
        rows: Sequence[Team],
        owner_names: Mapping[int, str],
    ) -> _TeamIdentity:
        """Derive the latest display name/owner/id and prior names for a franchise slot."""
        ordered = sorted(rows, key=lambda team: team.season)
        latest = ordered[-1]
        names: list[str] = []
        for team in ordered:
            if team.name not in names:
                names.append(team.name)
        aliases = tuple(name for name in names if name != latest.name)
        owner_name = owner_names.get(latest.owner_id) if latest.owner_id is not None else None
        return _TeamIdentity(
            team_key=team_key,
            team_id=latest.id,
            name=latest.name,
            owner_name=owner_name,
            aliases=aliases,
            first_season=ordered[0].season,
        )

    @staticmethod
    def _completed_weeks(
        season: int,
        regular_season_length: int,
        matchups_by_week: Mapping[tuple[int, int], Sequence[Matchup]],
    ) -> list[int]:
        """Return completed regular-season weeks, matching the standings definition."""
        weeks: list[int] = []
        for week in range(1, regular_season_length + 1):
            matchups = matchups_by_week.get((season, week), ())
            if not matchups:
                continue
            if any(matchup.is_playoff or not matchup.is_complete for matchup in matchups):
                continue
            weeks.append(week)
        return weeks

    @staticmethod
    def _league_week(
        *,
        season: int,
        week: int,
        cup_week: int | None,
        matchups: Sequence[Matchup],
        scores: Sequence[Score],
        team_key_by_id: Mapping[int, str],
        mode: EloMode,
    ) -> _LeagueWeekResult:
        """Build one domain week, warning instead of failing on a missing score."""
        scores_by_team = {score.team_id: score.points for score in scores}
        warning: str | None = None
        domain_matches: list[EloMatch] = []
        domain_scores: list[tuple[str, Decimal]] = []

        if mode == "actual_schedule":
            for matchup in matchups:
                if matchup.away_team_id is None:
                    continue
                home_key = team_key_by_id.get(matchup.home_team_id)
                away_key = team_key_by_id.get(matchup.away_team_id)
                if home_key is None or away_key is None:
                    continue
                home_points = scores_by_team.get(matchup.home_team_id)
                away_points = scores_by_team.get(matchup.away_team_id)
                if home_points is None or away_points is None:
                    warning = (
                        f"Season {season}, week {week} has a matchup with a missing score; "
                        "that matchup was skipped."
                    )
                    continue
                domain_matches.append(
                    EloMatch(
                        home_key=home_key,
                        away_key=away_key,
                        home_points=home_points,
                        away_points=away_points,
                        order=matchup.id,
                    )
                )
        else:
            for team_id, key in team_key_by_id.items():
                points = scores_by_team.get(team_id)
                if points is None:
                    warning = (
                        f"Season {season}, week {week} is missing at least one team score; "
                        "the round-robin week was not rated."
                    )
                    continue
                domain_scores.append((key, points))

        return _LeagueWeekResult(
            week=EloWeek(
                season=season,
                week=week,
                is_cup_week=week == cup_week,
                is_playoff=False,
                is_complete=True,
                matches=tuple(domain_matches),
                scores=tuple(sorted(domain_scores)),
            ),
            warning=warning,
        )


@dataclass(frozen=True)
class _LeagueWeekResult:
    """One domain week plus an optional user-facing warning about skipped stored data."""

    week: EloWeek
    warning: str | None


__all__ = [
    "EloHistoryView",
    "EloLeagueNotFoundError",
    "EloService",
    "EloTeamView",
    "EloUnratedTeam",
    "EloWarning",
    "InvalidEloConfigError",
    "EloSeasonRating",
    "EloWeekReference",
]
