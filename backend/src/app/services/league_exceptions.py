"""Typed exceptions raised by LeagueService operations."""


class LeagueServiceError(Exception):
    """Base class for expected league-service failures."""


class InvalidLeagueRequestError(LeagueServiceError):
    """The requested league id, season, or credential pair is not usable."""


class AdminRequiredError(LeagueServiceError):
    """A non-admin tried to add a league; members join only by redeeming a member invite."""


class InviteNotRedeemableError(LeagueServiceError):
    """The invite code is unknown, expired, wrong-role, or not bound to a league."""


class NotAMemberError(LeagueServiceError, LookupError):
    """The caller has no membership in the requested league."""


class AlreadyMemberError(LeagueServiceError):
    """The caller already holds a membership in the league."""


class OwnerNotFoundError(LeagueServiceError, LookupError):
    """The requested owner does not belong to the league."""


class LeagueMemberNotFoundError(LeagueServiceError, LookupError):
    """The requested user holds no membership in the league."""


class LastAdminError(LeagueServiceError):
    """Removing this member would leave the league with no admin member."""


class InvalidInviteRequestError(LeagueServiceError):
    """The requested invite role, league binding, or lifetime is not usable."""


class LeagueSeasonNotFoundError(LeagueServiceError, LookupError):
    """The league exists but the requested season is not stored."""


class InvalidCupWeekError(LeagueServiceError):
    """The cup week is outside 1..the season's stored regular-season length."""


class InvalidSeasonSettingsError(LeagueServiceError):
    """The season's stored metadata has no usable regular-season length."""


class CredentialsRequiredError(LeagueServiceError):
    """The caller's membership holds no credentials for a refresh or a new season."""


class DuplicateSeasonError(LeagueServiceError):
    """The league already stores data for the requested season."""


class IncompleteCredentialsError(InvalidLeagueRequestError):
    """Only one of the two ESPN cookies was supplied, or a supplied value is empty."""


class LeagueProviderError(LeagueServiceError):
    """The provider could not be configured or did not recognize the league season."""


class LeagueAccessError(LeagueProviderError):
    """The provider could not reach the league, as with a private league and no credentials."""


class LeagueSyncError(LeagueServiceError):
    """The provider-backed sync failed after validation."""


class RefreshRateLimitedError(LeagueServiceError):
    """The refresh was rejected by the per-league or per-user rate limit."""

    def __init__(self, retry_after: int) -> None:
        """Record the whole seconds a caller should wait before trying again."""
        self.retry_after = retry_after
        super().__init__("league refresh is rate limited")
