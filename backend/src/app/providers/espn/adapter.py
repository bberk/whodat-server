"""ESPN adapter implementing the LeagueProvider protocol.

This is the ONLY place that imports espn_api or contains ESPN-specific logic
(ARCHITECTURE.md section 3, AC-PR-03). All ESPN quirks (cookie auth, division
names, bye representation, playoff detection) are contained here and in the
mappers module.
"""

from collections.abc import Callable
from typing import Any

from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)
from app.providers.espn._types import ESPNLeagueProto
from app.providers.espn.mappers import (
    map_league,
    map_matchups,
    map_owners,
    map_teams,
)


class ESPNLeagueProvider:
    """ESPN adapter implementing the LeagueProvider protocol.

    The adapter accepts a league_factory callable for dependency injection.
    In production, this creates real espn_api.football.League objects. In
    tests, it returns pre-built fakes with fixture data.

    Credentials are always supplied explicitly by the credential factory in
    :mod:`app.providers.espn.credentials`. The adapter never reads them from the
    environment, so an omitted cookie stays empty (a public league).
    """

    provider_id = "espn"

    def __init__(
        self,
        *,
        league_factory: Callable[..., Any] | None = None,
        espn_s2: str | None = None,
        swid: str | None = None,
    ) -> None:
        """Initialize the ESPN adapter.

        Args:
            league_factory: Callable that creates league objects. If None,
                imports espn_api.football.League on first use.
            espn_s2: ESPN S2 cookie for private leagues, or None for no cookie.
            swid: ESPN SWID cookie for private leagues, or None for no cookie.
        """
        self._espn_s2 = espn_s2 or ""
        self._swid = swid or ""

        self._league_factory = league_factory
        # Cache: (external_id, season) -> league object
        self._cache: dict[tuple[str, int], ESPNLeagueProto] = {}

    def _make_league(self, league_ref: LeagueRef, season: int) -> ESPNLeagueProto:
        """Create or retrieve a cached league object.

        The factory is called with (league_id, year, espn_s2, swid).
        For espn_api.football.League, these map to positional args.
        """
        key = (league_ref.external_id, season)
        if key not in self._cache:
            if self._league_factory is None:
                # Lazy import to avoid importing espn_api at module load time
                from espn_api.football import League  # type: ignore[import-untyped]

                self._league_factory = League

            # Pass credentials only if both are present (private league)
            kwargs: dict[str, Any] = {}
            if self._espn_s2 and self._swid:
                kwargs["espn_s2"] = self._espn_s2
                kwargs["swid"] = self._swid

            league = self._league_factory(
                int(league_ref.external_id),
                season,
                **kwargs,
            )
            self._cache[key] = league
        return self._cache[key]

    def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO:
        """Return normalized league metadata for the requested season."""
        league = self._make_league(league_ref, season)
        return map_league(league, league_ref.external_id)

    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]:
        """Return owners for the requested league season."""
        league = self._make_league(league_ref, season)
        return map_owners(league)

    def fetch_teams(self, league_ref: LeagueRef, season: int) -> list[TeamDTO]:
        """Return teams for the requested league season."""
        league = self._make_league(league_ref, season)
        return map_teams(league)

    def fetch_matchups(self, league_ref: LeagueRef, season: int, week: int) -> list[MatchupDTO]:
        """Return normalized matchups for one week."""
        league = self._make_league(league_ref, season)
        return map_matchups(league, week)

    def current_week(self, league_ref: LeagueRef, season: int) -> WeekStatus:
        """Return the latest completed-week status for the league season.

        Returns the latest completed REGULAR-SEASON week, capped at the
        regular season length. Returns None if no weeks have completed yet.

        The provider uses ESPN's currentMatchupPeriod to determine the
        current week. Weeks 1..currentMatchupPeriod-1 are complete. If
        currentMatchupPeriod > regular_season_length, we're in playoffs,
        so cap at regular_season_length.
        """
        league = self._make_league(league_ref, season)
        current_period = league.currentMatchupPeriod
        regular_season_length = league.settings.reg_season_count

        # No completed weeks yet
        if current_period <= 1:
            return WeekStatus(last_completed_week=None)

        # In or past playoffs: cap at regular season length
        if current_period > regular_season_length:
            return WeekStatus(last_completed_week=regular_season_length)

        # Regular season in progress
        return WeekStatus(last_completed_week=current_period - 1)
