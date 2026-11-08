"""Data structures, views, and protocols for league operations."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.providers.base import LeagueProvider


@dataclass(frozen=True)
class LeagueUser:
    """The authenticated caller identity needed by this service."""

    user_id: int
    role: str


@dataclass(frozen=True)
class EspnCredentials:
    """Plaintext credentials supplied by an admin for one add-league request.

    The fields are excluded from ``repr`` so an accidental log or traceback does not expose them.
    The service encrypts them immediately and never stores or returns the plaintext.
    """

    espn_s2: str = field(repr=False)
    espn_swid: str = field(repr=False)


@dataclass(frozen=True)
class EncryptedCredentials:
    """Opaque credential tokens handed to the provider factory and stored on a membership."""

    espn_s2_encrypted: str = field(repr=False)
    espn_swid_encrypted: str = field(repr=False)


class ProviderFactory(Protocol):
    """Build a provider, decrypting only behind the provider layer when tokens are supplied."""

    def __call__(
        self,
        *,
        espn_s2_encrypted: str | None = None,
        espn_swid_encrypted: str | None = None,
    ) -> LeagueProvider: ...


@dataclass(frozen=True)
class MembershipView:
    """A membership and its league, safe to return to a browser."""

    league_id: int
    provider: str
    external_id: str
    name: str
    owner_id: int | None
    has_credentials: bool
    show_wapdate: bool
    has_trades_enabled: bool = False


@dataclass(frozen=True)
class OwnerView:
    """A league owner available for the caller's owner association."""

    id: int
    external_id: str
    display_name: str


@dataclass(frozen=True)
class CupWeekView:
    """One league season's cup week and the week range the admin UI offers.

    ``cup_week`` is ``None`` when the season has no cup week; ``regular_season_length`` comes from
    the season's stored metadata and bounds every non-null value.
    """

    season: int
    cup_week: int | None
    regular_season_length: int


@dataclass(frozen=True)
class SeasonSettingsView:
    """One stored season's admin settings, all safe to return to a browser.

    ``last_refreshed_at`` is ``None`` when the season has never been synced through the provider;
    the UI shows "Never". A cup-week edit never changes it.
    """

    season: int
    cup_week: int | None
    regular_season_length: int
    last_refreshed_at: datetime | None


@dataclass(frozen=True)
class LeagueMemberView:
    """One account associated with a league, with no credential or password material."""

    user_id: int
    email: str
    role: str
    owner_id: int | None
    owner_name: str | None
    has_credentials: bool


@dataclass(frozen=True)
class CreatedInviteView:
    """A freshly created invite and the raw code returned to the admin exactly once."""

    code: str = field(repr=False)
    role: str
    league_id: int | None
    expires_at: datetime


@dataclass(frozen=True)
class AddLeagueResult:
    """Outcome of adding or joining a league."""

    membership: MembershipView
    season: int
    weeks_synced: tuple[int, ...]


@dataclass(frozen=True)
class RefreshResult:
    """Outcome of a league-wide refresh."""

    league_id: int
    season: int
    weeks_synced: tuple[int, ...]
    weeks_with_vp_recomputed: tuple[int, ...]


@dataclass(frozen=True)
class AddSeasonResult:
    """Outcome of adding and syncing one season for an existing league."""

    league_id: int
    season: int
    weeks_synced: tuple[int, ...]


@dataclass(frozen=True)
class SeasonRefreshResult:
    """Outcome of refreshing exactly one stored season through the provider."""

    league_id: int
    season: int
    weeks_synced: tuple[int, ...]
