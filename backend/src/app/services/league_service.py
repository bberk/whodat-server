"""League membership, owner association, credential storage, and refresh.

The service is transaction-neutral with a documented commit boundary: every method flushes its
writes (through repositories or the sync service) but never commits. HTTP callers call
:meth:`LeagueService.commit` after a successful mutating request; the session dependency rolls the
request back when an exception escapes. Multi-step writes that must not survive a later failure
(a credentialed add, a refresh, and adding a season) additionally run inside a SAVEPOINT, so a
typed sync error never leaves a partial league, membership, season, or refresh behind even if a
caller commits afterwards.

Only an admin may add a league; members join an additional league by redeeming a valid, unexpired
member invite, never by supplying a bare league id. A member-invite redemption writes exactly one
membership (or nothing at all on an unknown, expired, wrong-role, or league-less invite).

Credential handling follows the provider boundary: the service encrypts request credentials with
:mod:`app.security.crypto` immediately and only ever passes ciphertext to the injected provider
factory. It never decrypts a stored token and never logs or returns a credential value. The
factory (production: :func:`app.providers.espn.credentials.create_espn_provider`) owns decryption.

Errors are typed so routers can map them to structured responses. Error messages are fixed and
never include cookie values, ciphertext, password material, invite codes, or provider exception
text.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.auth_repositories import DuplicateMembershipError as DatabaseDuplicateMembershipError
from app.db.auth_repositories import InviteRepository, MembershipRepository
from app.db.models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    VALID_ROLES,
    AppUser,
    Invite,
    League,
    LeagueEloConfig,
    LeagueSeason,
    Matchup,
    Owner,
    Score,
    Team,
    UserLeague,
)
from app.db.repositories import SyncRepository
from app.providers.base import LeagueDTO, LeagueProvider, LeagueRef
from app.security.crypto import CredentialCryptoError, encrypt
from app.security.invite_codes import (
    DEFAULT_INVITE_LIFETIME_DAYS,
    MAX_INVITE_LIFETIME_DAYS,
    generate_invite_code,
    hash_invite_code,
    invite_code_matches,
)
from app.services.sync_service import (
    PROVIDER_CONFIG_REF,
    SyncError,
    SyncService,
    SyncSummary,
)
from app.validation import normalize_external_id

#: The only provider the HTTP API currently stores leagues for.
PROVIDER_ID = "espn"

#: A league-wide refresh is allowed once per league in this interval.
DEFAULT_LEAGUE_REFRESH_INTERVAL_SECONDS = 5 * 60.0

#: A user may trigger this many refreshes in the rolling window below.
DEFAULT_USER_REFRESH_LIMIT = 3

#: Rolling window for the per-user refresh limit.
DEFAULT_USER_REFRESH_WINDOW_SECONDS = 60 * 60.0


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


@dataclass(frozen=True)
class RefreshRateLimitDecision:
    """Outcome of one league-refresh rate-limit check."""

    allowed: bool
    retry_after: int


class RefreshRateLimiter:
    """A thread-safe refresh limiter with independent per-league and per-user limits.

    The defaults allow one refresh per league every five minutes and three refreshes per user per
    rolling hour. The clock is injectable (seconds, monotonically non-decreasing in tests) so the
    behaviour is deterministic. A denied attempt does not consume quota; an allowed attempt is
    recorded before the provider call, so a failed sync still counts.

    State is process-local, like the auth limiter: a multi-worker deployment needs a shared store.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        league_interval_seconds: float = DEFAULT_LEAGUE_REFRESH_INTERVAL_SECONDS,
        user_limit: int = DEFAULT_USER_REFRESH_LIMIT,
        user_window_seconds: float = DEFAULT_USER_REFRESH_WINDOW_SECONDS,
    ) -> None:
        """Configure the limits and clock; non-negative intervals and a positive limit are valid."""
        if league_interval_seconds < 0:
            raise ValueError("league_interval_seconds must not be negative")
        if user_limit < 1:
            raise ValueError("user_limit must be at least 1")
        if user_window_seconds <= 0:
            raise ValueError("user_window_seconds must be positive")
        self._clock = clock
        self._league_interval_seconds = float(league_interval_seconds)
        self._user_limit = user_limit
        self._user_window_seconds = float(user_window_seconds)
        self._last_league_refresh: dict[int, float] = {}
        self._user_attempts: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, *, league_id: int, user_id: int) -> RefreshRateLimitDecision:
        """Record one allowed refresh or report how long the caller must wait.

        Both limits are evaluated before either counter changes, so a denial by one limit does not
        consume the other. ``retry_after`` is the largest whole-second wait implied by the two
        limits (at least one when denied).
        """
        now = float(self._clock())
        with self._lock:
            league_retry = self._league_retry(league_id, now)
            attempts = [
                attempt
                for attempt in self._user_attempts.get(user_id, [])
                if now - attempt < self._user_window_seconds
            ]
            self._user_attempts[user_id] = attempts
            user_retry = self._user_retry(attempts, now)

            if league_retry > 0 or user_retry > 0:
                return RefreshRateLimitDecision(
                    allowed=False, retry_after=max(league_retry, user_retry)
                )

            self._last_league_refresh[league_id] = now
            attempts.append(now)
            return RefreshRateLimitDecision(allowed=True, retry_after=0)

    def reset(self) -> None:
        """Forget every counter (used by tests and administrative resets)."""
        with self._lock:
            self._last_league_refresh.clear()
            self._user_attempts.clear()

    def _league_retry(self, league_id: int, now: float) -> int:
        """Return whole seconds until this league may refresh again, or zero when allowed."""
        last = self._last_league_refresh.get(league_id)
        if last is None or now >= last + self._league_interval_seconds:
            return 0
        return max(1, math.ceil(last + self._league_interval_seconds - now))

    def _user_retry(self, attempts: list[float], now: float) -> int:
        """Return whole seconds until this user's oldest attempt leaves the window, or zero."""
        if len(attempts) < self._user_limit:
            return 0
        return max(1, math.ceil(attempts[0] + self._user_window_seconds - now))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware timestamp so the API always emits an unambiguous ISO instant.

    SQLite does not preserve timezone information, so a value read back there is naive; it was
    written as UTC, and this restores the marker. Postgres already returns an aware value.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class LeagueService:
    """Add and join leagues, list membership-scoped data, and refresh using stored credentials."""

    def __init__(
        self,
        session: Session,
        provider_factory: ProviderFactory,
        *,
        provider_id: str = PROVIDER_ID,
        refresh_limiter: RefreshRateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind the service to a caller-owned session and an injected credential-backed factory."""
        self._session = session
        self._provider_factory = provider_factory
        self._provider_id = provider_id
        self._refresh_limiter = refresh_limiter or RefreshRateLimiter()
        self._clock = clock or _utc_now
        self._memberships = MembershipRepository(session)
        self._invites = InviteRepository(session)
        self._sync = SyncRepository(session)

    def commit(self) -> None:
        """Commit the caller's current unit of work (the service never commits on its own)."""
        self._session.commit()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_league(
        self,
        user: LeagueUser,
        espn_league_id: str,
        season: int | None = None,
        credentials: EspnCredentials | None = None,
    ) -> AddLeagueResult:
        """Add a league as an admin; members join only by redeeming a member invite.

        The account must be an admin (AC-AU-06/08); a member's request is rejected before any
        provider call or write. The credentials are encrypted before use, the provider is
        constructed and the requested season is fetched, and only after that validation succeeds
        are the league, membership, encrypted tokens, and initial sync written inside one
        SAVEPOINT. A duplicate membership is rejected before any provider call.

        Without credentials, an admin may add a brand-new public league: the provider is built with
        explicit empty cookies, the league season is fetched before any write, and the membership is
        stored without credentials. The caller commits.
        """
        try:
            external_id = normalize_external_id(espn_league_id)
        except ValueError:
            raise InvalidLeagueRequestError("espn_league_id is not a valid id") from None
        requested_season = self._clock().year if season is None else season
        if requested_season <= 0:
            raise InvalidLeagueRequestError("season must be a positive year")

        if user.role != ROLE_ADMIN:
            raise AdminRequiredError("only an admin may add a league")

        existing = self._sync.get_league(self._provider_id, external_id)
        if existing is not None and self._memberships.get(user.user_id, existing.id) is not None:
            raise AlreadyMemberError("user already belongs to this league")

        if credentials is None:
            if existing is not None:
                membership = self._create_membership(user.user_id, existing.id)
                return AddLeagueResult(
                    membership=self._view(membership),
                    season=requested_season,
                    weeks_synced=(),
                )
            provider = self._build_provider(None)
            league_dto = self._fetch_league(
                provider, external_id, requested_season, using_credentials=False
            )
            return self._persist_new_league(
                user, external_id, requested_season, provider, league_dto, None
            )

        encrypted = self._encrypt_credentials(credentials)
        provider = self._build_provider(encrypted)
        league_dto = self._fetch_league(
            provider, external_id, requested_season, using_credentials=True
        )
        return self._persist_new_league(
            user, external_id, requested_season, provider, league_dto, encrypted
        )

    def redeem_invite(self, user: LeagueUser, invite_code: str) -> MembershipView:
        """Join the league named by a valid member invite, creating exactly one membership.

        The code is validated against its stored hash and the invite must be unexpired, carry the
        member role, and name a league; any other state raises
        :class:`InviteNotRedeemableError` before a write. A caller who already belongs to the
        league raises :class:`AlreadyMemberError`. The raw code is never stored, logged, or
        returned. The caller commits.
        """
        expected_hash = hash_invite_code(invite_code) if invite_code else ""
        invite = self._invites.get_by_code_hash(expected_hash) if expected_hash else None
        if invite is None or not invite_code_matches(invite_code, invite.code_hash):
            raise InviteNotRedeemableError("invite code is invalid or expired")
        if not self._invites.is_valid(invite, now=self._clock()):
            raise InviteNotRedeemableError("invite code is invalid or expired")
        if invite.role != ROLE_MEMBER or invite.league_id is None:
            raise InviteNotRedeemableError("invite code is invalid or expired")
        if self._memberships.get(user.user_id, invite.league_id) is not None:
            raise AlreadyMemberError("user already belongs to this league")
        membership = self._create_membership(user.user_id, invite.league_id)
        return self._view(membership)

    def set_owner(
        self,
        user: LeagueUser,
        league_id: int,
        owner_id: int | None,
    ) -> MembershipView:
        """Set or clear the owner association on the caller's own membership.

        The owner must belong to the same league. No other user's membership can be addressed.
        """
        self.require_membership(user, league_id)
        if owner_id is not None:
            owner = self._session.scalar(
                select(Owner).where(Owner.id == owner_id, Owner.league_id == league_id)
            )
            if owner is None:
                raise OwnerNotFoundError("owner does not belong to this league")
        membership = self._memberships.set_owner(user.user_id, league_id, owner_id)
        return self._view(membership)

    def get_cup_week(self, user: LeagueUser, league_id: int, season: int) -> CupWeekView:
        """Return a stored season's cup week and its regular-season length.

        Membership is required first, so a non-member receives the same 404 as every other
        league-scoped read. The length comes from the stored season metadata; the UI uses it to
        build the week choices without inventing a setting.
        """
        self.require_membership(user, league_id)
        league_season = self._require_league_season(league_id, season)
        return CupWeekView(
            season=league_season.season,
            cup_week=league_season.cup_week,
            regular_season_length=self._regular_season_length(league_season),
        )

    def set_cup_week(
        self,
        user: LeagueUser,
        league_id: int,
        season: int,
        cup_week: int | None,
    ) -> CupWeekView:
        """Set or clear a season's cup week and recompute its stored weeks in one operation.

        The caller must be a league member (non-members get the same 404 as other league reads)
        and an admin. A non-null value must be between 1 and the season's stored regular-season
        length, read from ``league_season`` metadata. The value is persisted and every stored
        complete, non-playoff week is recomputed from stored data before the caller commits, so
        season totals and stored score rows agree with the new cup week.
        """
        membership = self.require_membership(user, league_id)
        if user.role != ROLE_ADMIN:
            raise AdminRequiredError("only an admin may change the cup week")
        league_season = self._require_league_season(league_id, season)
        regular_season_length = self._regular_season_length(league_season)
        if cup_week is not None and not 1 <= cup_week <= regular_season_length:
            raise InvalidCupWeekError(f"cup_week must be between 1 and {regular_season_length}")

        with self._session.begin_nested():
            league_season.cup_week = cup_week
            self._session.flush()
            try:
                SyncService(None, self._session).recompute_league(
                    LeagueRef(external_id=membership.league.external_id),
                    self._provider_id,
                    season,
                )
            except SyncError:
                raise LeagueSyncError("league VP could not be recomputed") from None

        return CupWeekView(
            season=league_season.season,
            cup_week=league_season.cup_week,
            regular_season_length=regular_season_length,
        )

    def refresh(self, user: LeagueUser, league_id: int) -> RefreshResult:
        """Refresh the league's most recent stored season with the membership's credentials.

        The caller must be a member whose membership holds both encrypted tokens. The provider is
        built from ciphertext (decryption stays behind the provider factory) and the sync runs
        inside a SAVEPOINT so a failure does not leave a partial refresh. Rate limits are checked
        per league and per user before the provider call; a denied request raises
        :class:`RefreshRateLimitedError` with the retry-after seconds.
        """
        membership = self.require_membership(user, league_id)
        espn_s2_encrypted = membership.espn_s2_encrypted
        espn_swid_encrypted = membership.espn_swid_encrypted
        if not espn_s2_encrypted or not espn_swid_encrypted:
            raise CredentialsRequiredError("membership holds no league credentials")

        decision = self._refresh_limiter.check(league_id=league_id, user_id=user.user_id)
        if not decision.allowed:
            raise RefreshRateLimitedError(decision.retry_after)

        encrypted = EncryptedCredentials(
            espn_s2_encrypted=espn_s2_encrypted,
            espn_swid_encrypted=espn_swid_encrypted,
        )
        provider = self._build_provider(encrypted)
        season = self._current_season(league_id)
        external_id = membership.league.external_id
        with self._session.begin_nested():
            summary = self._sync_season(provider, external_id, season)

        return RefreshResult(
            league_id=league_id,
            season=season,
            weeks_synced=summary.weeks_synced,
            weeks_with_vp_recomputed=summary.weeks_with_vp_recomputed,
        )

    def add_season(self, user: LeagueUser, league_id: int, season: int) -> AddSeasonResult:
        """Add and sync one more season for an existing league the caller administers.

        The caller must hold a membership in the league (a non-member gets the same error as an
        unknown league, so the response does not confirm that it exists) and have the global admin
        role. The season must not already be stored, and the caller's own membership must hold both
        encrypted ESPN cookies: there is no fallback to another member's credentials or to the
        environment. The provider is built from ciphertext, exactly as for a refresh, so decryption
        stays behind the provider factory.

        The provider-backed sync runs inside a SAVEPOINT, so a provider failure leaves no league,
        season, owner, team, matchup, or score rows from this request even if a caller commits
        afterwards. The caller commits on success.
        """
        membership = self.require_membership(user, league_id)
        if user.role != ROLE_ADMIN:
            raise AdminRequiredError("only an admin may add a season")
        if season <= 0:
            raise InvalidLeagueRequestError("season must be a positive year")
        if self._sync.get_league_season(league_id, season) is not None:
            raise DuplicateSeasonError("season is already stored for this league")

        espn_s2_encrypted = membership.espn_s2_encrypted
        espn_swid_encrypted = membership.espn_swid_encrypted
        if not espn_s2_encrypted or not espn_swid_encrypted:
            raise CredentialsRequiredError("membership holds no league credentials")

        encrypted = EncryptedCredentials(
            espn_s2_encrypted=espn_s2_encrypted,
            espn_swid_encrypted=espn_swid_encrypted,
        )
        provider = self._build_provider(encrypted)
        external_id = membership.league.external_id
        with self._session.begin_nested():
            summary = self._sync_season(provider, external_id, season)

        return AddSeasonResult(
            league_id=league_id,
            season=season,
            weeks_synced=summary.weeks_synced,
        )

    def list_season_settings(self, user: LeagueUser, league_id: int) -> list[SeasonSettingsView]:
        """Return every stored season's admin settings for an admin member.

        The caller must belong to the league (a non-member gets the same 404 as every other
        league-scoped read) and hold the global admin role. Seasons are ordered ascending. A season
        that has never synced through the provider reports ``last_refreshed_at=None``; the cup week
        and regular-season length come from the stored season row, and no provider is contacted.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        return [
            SeasonSettingsView(
                season=row.season,
                cup_week=row.cup_week,
                regular_season_length=self._regular_season_length(row),
                last_refreshed_at=_as_utc(row.last_refreshed_at),
            )
            for row in self._sync.list_league_seasons(league_id)
        ]

    def refresh_season(self, user: LeagueUser, league_id: int, season: int) -> SeasonRefreshResult:
        """Refresh exactly one stored season using the caller's own stored credentials.

        Only an admin member may call this. The season must already be stored, so a refresh never
        invents or duplicates a season, and the provider is built from the caller's membership
        ciphertext exactly as for the league-wide refresh. Rate limits are checked per league and
        per user before the provider call. A successful sync records the season's
        ``last_refreshed_at``; a failure rolls the SAVEPOINT back and changes neither scores nor the
        timestamp.
        """
        membership = self.require_membership(user, league_id)
        self._require_admin(user)
        self._require_league_season(league_id, season)
        espn_s2_encrypted = membership.espn_s2_encrypted
        espn_swid_encrypted = membership.espn_swid_encrypted
        if not espn_s2_encrypted or not espn_swid_encrypted:
            raise CredentialsRequiredError("membership holds no league credentials")

        decision = self._refresh_limiter.check(league_id=league_id, user_id=user.user_id)
        if not decision.allowed:
            raise RefreshRateLimitedError(decision.retry_after)

        encrypted = EncryptedCredentials(
            espn_s2_encrypted=espn_s2_encrypted,
            espn_swid_encrypted=espn_swid_encrypted,
        )
        provider = self._build_provider(encrypted)
        external_id = membership.league.external_id
        with self._session.begin_nested():
            summary = self._sync_season(provider, external_id, season)

        return SeasonRefreshResult(
            league_id=league_id,
            season=season,
            weeks_synced=summary.weeks_synced,
        )

    def delete_season(self, user: LeagueUser, league_id: int, season: int) -> None:
        """Delete one stored season's data, leaving the league and every other season intact.

        Only an admin member may delete a season. Rows are removed child-first (scores, matchups,
        teams, then the season itself) so the operation satisfies foreign-key enforcement on both
        SQLite and Postgres. Owners, memberships, invites, the league row, and every other stored
        season are untouched. The whole delete runs in a SAVEPOINT; the caller commits on success.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        league_season = self._require_league_season(league_id, season)
        with self._session.begin_nested():
            for model in (Score, Matchup, Team):
                self._session.execute(
                    delete(model).where(model.league_id == league_id, model.season == season)
                )
            self._session.delete(league_season)
            self._session.flush()

    # ------------------------------------------------------------------
    # League administration
    # ------------------------------------------------------------------

    def list_members(self, user: LeagueUser, league_id: int) -> list[LeagueMemberView]:
        """List every account associated with a league, for an admin member.

        A non-member receives the same 404 as every other league-scoped read; a member without the
        admin role receives 403. Email is the account identifier because the application stores no
        username. The response says only whether a membership holds stored credentials; neither a
        credential nor a password hash ever leaves this method.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        rows = self._session.execute(
            select(UserLeague, AppUser, Owner)
            .join(AppUser, AppUser.id == UserLeague.user_id)
            .outerjoin(Owner, Owner.id == UserLeague.owner_id)
            .where(UserLeague.league_id == league_id)
            .order_by(AppUser.email)
        ).all()
        return [
            LeagueMemberView(
                user_id=account.id,
                email=account.email,
                role=account.role,
                owner_id=membership.owner_id,
                owner_name=owner.display_name if owner is not None else None,
                has_credentials=bool(
                    membership.espn_s2_encrypted and membership.espn_swid_encrypted
                ),
            )
            for membership, account, owner in rows
        ]

    def remove_member(self, user: LeagueUser, league_id: int, member_user_id: int) -> None:
        """Remove one user's membership in a league, leaving the account and other leagues alone.

        Only an admin member may remove someone. An admin may remove themselves or another admin,
        but the removal is refused when it would leave the league with zero admin members, because
        nobody could administer the league afterwards. The owner association and any encrypted
        credentials live on the membership row, so deleting the row removes them; the account and
        every other membership are untouched. The caller commits.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        membership = self._memberships.get(member_user_id, league_id)
        if membership is None:
            raise LeagueMemberNotFoundError("that user is not a member of this league")
        account = self._session.get(AppUser, member_user_id)
        if (
            account is None
        ):  # pragma: no cover - unreachable: user_league.user_id is a FK (AC-AU-20)
            raise LeagueMemberNotFoundError("that user is not a member of this league")
        if account.role == ROLE_ADMIN and self._admin_member_count(league_id) <= 1:
            raise LastAdminError("a league must keep at least one admin member")
        self._session.delete(membership)
        self._session.flush()

    def create_invite(
        self,
        user: LeagueUser,
        league_id: int,
        role: str,
        expires_in_days: int | None = None,
    ) -> CreatedInviteView:
        """Create one invite from the admin page and return its raw code exactly once.

        A ``member`` invite is bound to this league; an ``admin`` invite is deliberately
        league-less so it can create an account that starts without a league. The lifetime defaults
        to seven days and is bounded. Only the code hash is stored, so the returned code cannot be
        retrieved again. Membership and admin checks match every other league-scoped write. The
        caller commits.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        if role not in VALID_ROLES:
            raise InvalidInviteRequestError("unknown invite role")
        days = DEFAULT_INVITE_LIFETIME_DAYS if expires_in_days is None else expires_in_days
        if not 1 <= days <= MAX_INVITE_LIFETIME_DAYS:
            raise InvalidInviteRequestError("invite lifetime is out of range")
        invite_league_id = league_id if role == ROLE_MEMBER else None
        code = generate_invite_code()
        with self._session.begin_nested():
            invite = self._invites.create(
                invite_league_id,
                hash_invite_code(code),
                self._clock() + timedelta(days=days),
                role=role,
            )
        return CreatedInviteView(
            code=code,
            role=invite.role,
            league_id=invite.league_id,
            expires_at=invite.expires_at,
        )

    def delete_league(self, user: LeagueUser, league_id: int) -> None:
        """Delete a league and every row that belongs to it, in one transaction.

        The caller must be an admin member; a non-member gets the same 404 as any league read. Rows
        are deleted child-first so the operation also succeeds where foreign keys are enforced
        (Postgres): scores, matchups, teams, memberships, owners, invites bound to this league,
        seasons, Elo settings, then the league itself. Accounts and league-less admin invites are
        not touched, and neither is any other league. The caller commits.
        """
        self.require_membership(user, league_id)
        self._require_admin(user)
        with self._session.begin_nested():
            for model in (
                Score,
                Matchup,
                Team,
                UserLeague,
                Owner,
                Invite,
                LeagueSeason,
                LeagueEloConfig,
            ):
                self._session.execute(delete(model).where(model.league_id == league_id))
            self._session.execute(delete(League).where(League.id == league_id))
            self._session.flush()

    # ------------------------------------------------------------------
    # Membership-scoped reads
    # ------------------------------------------------------------------

    def require_membership(self, user: LeagueUser, league_id: int) -> UserLeague:
        """Return the caller's membership or raise :class:`NotAMemberError`.

        Routers map this error to 404 (a non-member learns nothing about the league) and rely on
        the auth dependency for the 401 case.
        """
        membership = self._memberships.get(user.user_id, league_id)
        if membership is None:
            raise NotAMemberError("caller is not a member of this league")
        return membership

    def list_memberships(self, user: LeagueUser) -> list[MembershipView]:
        """Return every league the caller belongs to, without credential values."""
        memberships = self._memberships.list_for_user(user.user_id)
        return [self._view(membership) for membership in memberships]

    def list_seasons(self, user: LeagueUser, league_id: int) -> list[int]:
        """Return the stored seasons for a league the caller belongs to, ascending."""
        self.require_membership(user, league_id)
        return [row.season for row in self._sync.list_league_seasons(league_id)]

    def list_owners(self, user: LeagueUser, league_id: int) -> list[OwnerView]:
        """Return the league's owners for a member to choose from."""
        self.require_membership(user, league_id)
        owners = self._session.scalars(
            select(Owner).where(Owner.league_id == league_id).order_by(Owner.id)
        )
        return [
            OwnerView(id=owner.id, external_id=owner.external_id, display_name=owner.display_name)
            for owner in owners
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _require_admin(user: LeagueUser) -> None:
        """Raise :class:`AdminRequiredError` unless the caller holds the global admin role."""
        if user.role != ROLE_ADMIN:
            raise AdminRequiredError("only an admin may administer this league")

    def _admin_member_count(self, league_id: int) -> int:
        """Count the league's members whose account role is ``admin``."""
        count = self._session.scalar(
            select(func.count())
            .select_from(UserLeague)
            .join(AppUser, AppUser.id == UserLeague.user_id)
            .where(UserLeague.league_id == league_id, AppUser.role == ROLE_ADMIN)
        )
        return int(count or 0)

    def _require_league_season(self, league_id: int, season: int) -> LeagueSeason:
        """Return the stored league season or raise :class:`LeagueSeasonNotFoundError`."""
        league_season = self._sync.get_league_season(league_id, season)
        if league_season is None:
            raise LeagueSeasonNotFoundError("season is not stored for this league")
        return league_season

    @staticmethod
    def _regular_season_length(league_season: LeagueSeason) -> int:
        """Return the season's stored regular-season length or raise a typed settings error.

        A non-integer, boolean, or non-positive value is not usable, so the admin UI never offers
        an invented week range.
        """
        raw: object = league_season.league_season_metadata.get("regular_season_length")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise InvalidSeasonSettingsError(
                "the season has no usable regular_season_length setting"
            )
        return raw

    def _create_membership(self, user_id: int, league_id: int) -> UserLeague:
        """Create a membership and translate a duplicate constraint into a typed error."""
        try:
            return self._memberships.create(user_id, league_id)
        except DatabaseDuplicateMembershipError:
            raise AlreadyMemberError("user already belongs to this league") from None

    def _persist_new_league(
        self,
        user: LeagueUser,
        external_id: str,
        season: int,
        provider: LeagueProvider,
        league_dto: LeagueDTO,
        encrypted: EncryptedCredentials | None,
    ) -> AddLeagueResult:
        """Write a new league, its membership, optional credentials, and initial sync atomically.

        The SAVEPOINT guarantees that a failed sync or unexpected write error leaves no league or
        membership row, whether or not the caller commits after catching the error.
        """
        try:
            with self._session.begin_nested():
                league = self._sync.upsert_league(
                    provider=self._provider_id,
                    external_id=league_dto.external_id,
                    name=league_dto.name,
                    league_metadata=dict(league_dto.metadata),
                    provider_config_ref=PROVIDER_CONFIG_REF,
                ).row
                membership = self._create_membership(user.user_id, league.id)
                if encrypted is not None:
                    self._memberships.set_credentials(
                        user.user_id,
                        league.id,
                        espn_s2_encrypted=encrypted.espn_s2_encrypted,
                        espn_swid_encrypted=encrypted.espn_swid_encrypted,
                    )
                summary = self._sync_season(provider, external_id, season)
        except LeagueServiceError:
            raise
        except Exception:
            raise LeagueSyncError("league data could not be synced") from None

        return AddLeagueResult(
            membership=self._view(membership),
            season=season,
            weeks_synced=summary.weeks_synced,
        )

    def _encrypt_credentials(self, credentials: EspnCredentials) -> EncryptedCredentials:
        """Encrypt the supplied cookies; plaintext never reaches storage or the provider factory."""
        if not credentials.espn_s2.strip() or not credentials.espn_swid.strip():
            raise IncompleteCredentialsError("both ESPN cookies are required")
        try:
            return EncryptedCredentials(
                espn_s2_encrypted=encrypt(credentials.espn_s2),
                espn_swid_encrypted=encrypt(credentials.espn_swid),
            )
        except CredentialCryptoError:
            raise LeagueProviderError("league credentials could not be secured") from None

    def _build_provider(self, credentials: EncryptedCredentials | None) -> LeagueProvider:
        """Build a provider, hiding every failure detail from the caller.

        ``None`` asks the factory for a no-credential (public) provider. Stored ciphertext is
        passed through unchanged; decryption stays inside the provider factory.
        """
        try:
            if credentials is None:
                return self._provider_factory()
            return self._provider_factory(
                espn_s2_encrypted=credentials.espn_s2_encrypted,
                espn_swid_encrypted=credentials.espn_swid_encrypted,
            )
        except Exception:
            raise LeagueProviderError("league provider could not be configured") from None

    def _fetch_league(
        self,
        provider: LeagueProvider,
        external_id: str,
        season: int,
        *,
        using_credentials: bool,
    ) -> LeagueDTO:
        """Validate the league season before any write.

        A no-credential admin add combines this check with the provider's access rules: a private
        league (or any unreachable league) fails with a typed access error and no rows are written.
        """
        try:
            return provider.fetch_league(LeagueRef(external_id=external_id), season)
        except Exception:
            if using_credentials:
                raise LeagueProviderError(
                    "league could not be validated with the supplied credentials"
                ) from None
            raise LeagueAccessError(
                "league could not be reached; private leagues require ESPN credentials"
            ) from None

    def _sync_season(self, provider: LeagueProvider, external_id: str, season: int) -> SyncSummary:
        """Run one provider-backed sync and translate every failure into a typed sync error."""
        try:
            return SyncService(provider, self._session, clock=self._clock).sync_league(
                LeagueRef(external_id=external_id),
                self._provider_id,
                season,
            )
        except SyncError:
            raise LeagueSyncError("league data could not be synced") from None
        except Exception:
            raise LeagueSyncError("league data could not be synced") from None

    def _current_season(self, league_id: int) -> int:
        """Return the most recent stored season, falling back to the clock's year."""
        seasons = self._sync.list_league_seasons(league_id)
        if not seasons:
            return self._clock().year
        return max(row.season for row in seasons)

    def _view(self, membership: UserLeague) -> MembershipView:
        """Project a membership and its league into a credential-free view."""
        league: League = membership.league
        return MembershipView(
            league_id=league.id,
            provider=league.provider,
            external_id=league.external_id,
            name=league.name,
            owner_id=membership.owner_id,
            has_credentials=bool(membership.espn_s2_encrypted and membership.espn_swid_encrypted),
        )
