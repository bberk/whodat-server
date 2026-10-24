"""Provider-agnostic data transfer objects and the league provider contract."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class LeagueRef:
    """Identify a league within the provider instance handling it."""

    external_id: str


@dataclass(frozen=True)
class LeagueDTO:
    """Represent normalized league metadata returned by a provider."""

    external_id: str
    name: str
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class OwnerDTO:
    """Represent a normalized league owner."""

    external_id: str
    display_name: str


@dataclass(frozen=True)
class TeamDTO:
    """Represent a normalized team and its optional owner and division."""

    external_id: str
    name: str
    division: str | None
    owner_external_id: str | None


@dataclass(frozen=True)
class MatchupSideDTO:
    """Represent one team's matchup slot and its score when the game has a result.

    Future matchups have ``points=None``: their zero-looking provider score is not a result and
    must not become a stored team-week score.
    """

    team_external_id: str
    points: Decimal | None


@dataclass(frozen=True)
class MatchupDTO:
    """Represent a weekly matchup; an absent away side denotes a bye."""

    week: int
    home: MatchupSideDTO
    away: MatchupSideDTO | None
    is_playoff: bool
    is_complete: bool


@dataclass(frozen=True)
class WeekStatus:
    """Identify the latest completed week, or None when none has completed."""

    last_completed_week: int | None


class LeagueProvider(Protocol):
    """Define the normalized league data operations required by sync services."""

    provider_id: str

    def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO:
        """Return normalized league metadata for the requested season."""
        ...

    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]:
        """Return owners for the requested league season."""
        ...

    def fetch_teams(self, league_ref: LeagueRef, season: int) -> list[TeamDTO]:
        """Return teams for the requested league season."""
        ...

    def fetch_matchups(self, league_ref: LeagueRef, season: int, week: int) -> list[MatchupDTO]:
        """Return normalized matchups for one week."""
        ...

    def current_week(self, league_ref: LeagueRef, season: int) -> WeekStatus:
        """Return the latest completed-week status for the league season."""
        ...
