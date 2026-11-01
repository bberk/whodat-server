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
    """Represent a normalized team and its optional owner and division.

    ``final_standing`` is the provider's final finishing position for the season, including
    playoffs (1 = champion). It is ``None`` while the provider has not reported one, so a season
    in progress never produces a champion or a podium.
    """

    external_id: str
    name: str
    division: str | None
    owner_external_id: str | None
    final_standing: int | None = None


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
class ProjectionSideDTO:
    """Represent one team's provider-projected score for a week.

    ``points`` is ``None`` when the provider has no usable projection (a missing lineup, a
    sentinel such as ``-1``, or an unparseable value). A projection is provider-supplied data,
    never a result and never a zero fill.
    """

    team_external_id: str
    points: Decimal | None


@dataclass(frozen=True)
class ProjectionDTO:
    """Represent one matchup's projected team scores for a single week.

    An absent away side denotes a bye; its projection is irrelevant for that team.
    """

    week: int
    home: ProjectionSideDTO
    away: ProjectionSideDTO | None
    is_playoff: bool


class ProviderError(Exception):
    """Base class for a provider call that failed for a reason a caller may report."""


class ProviderAuthError(ProviderError):
    """The provider rejected the supplied credentials.

    The unattended refresh job rotates to a different credential-holding membership on this
    error. Never include cookie values, ciphertext, or an email in the message.
    """


class ProviderLeagueNotFound(ProviderError):
    """The provider does not know the requested league (or the caller cannot see it)."""


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

    def fetch_projections(
        self, league_ref: LeagueRef, season: int, week: int
    ) -> list[ProjectionDTO]:
        """Return provider-projected team scores for one week.

        Providers that cannot expose projections return an empty list rather than inventing
        scores. A projection is not a result and never substitutes for a stored score.
        """
        ...

    def current_week(self, league_ref: LeagueRef, season: int) -> WeekStatus:
        """Return the latest completed-week status for the league season."""
        ...
