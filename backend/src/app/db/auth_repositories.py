"""Typed, transaction-neutral repositories for accounts, invites, and memberships.

Like :mod:`app.db.repositories`, these repositories flush their writes so generated ids are
visible to later calls in the same session. They never commit or roll back: transaction ownership
belongs to the calling service. A caller that wants to continue after a duplicate write must roll
back the failed transaction itself.

These repositories store and clear already-encrypted credential tokens. They never import the
security layer, decrypt values, or log them.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ROLE_MEMBER, AppUser, Invite, UserLeague

_APP_USER_EMAIL_CONSTRAINTS = (
    "UNIQUE constraint failed: app_user.email",
    "uq_app_user_email",
)
_USER_LEAGUE_CONSTRAINTS = (
    "UNIQUE constraint failed: user_league.user_id, user_league.league_id",
    "uq_user_league_user_id_league_id",
)


class DuplicateEmailError(ValueError):
    """Raised when an account cannot be created because its email already exists."""


class DuplicateMembershipError(ValueError):
    """Raised when a user already holds a membership in the league."""


class MembershipNotFoundError(LookupError):
    """Raised when no membership exists for a user and league pair."""


def _normalize_email(email: str) -> str:
    """Return the stored form of an email address (trimmed and lowercase).

    Empty or whitespace-only addresses are rejected before they reach the unique constraint.
    """
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email must not be empty")
    return normalized


def _is_unique_violation(error: IntegrityError, markers: tuple[str, ...]) -> bool:
    """Report whether an integrity error came from the expected unique constraint.

    SQLite and Postgres word constraint violations differently, so both the table.column form and
    the constraint name are accepted.
    """
    message = str(error.orig)
    return any(marker in message for marker in markers)


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so SQLite and Postgres compare expiry consistently."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UserRepository:
    """Create and look up accounts using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        """Bind repository methods to a session without taking transaction ownership."""
        self._session = session

    def create(self, email: str, password_hash: str, role: str = ROLE_MEMBER) -> AppUser:
        """Create a user with a lowercase email.

        Raises :class:`DuplicateEmailError` when the email is already taken, including when the
        existing account used different letter casing.
        """
        user = AppUser(email=_normalize_email(email), password_hash=password_hash, role=role)
        self._session.add(user)
        try:
            self._session.flush()
        except IntegrityError as error:
            if _is_unique_violation(error, _APP_USER_EMAIL_CONSTRAINTS):
                raise DuplicateEmailError("an account with this email already exists") from None
            raise
        return user

    def get_by_email(self, email: str) -> AppUser | None:
        """Return the account for a case-insensitive email lookup, if one exists."""
        return self._session.scalar(select(AppUser).where(AppUser.email == _normalize_email(email)))

    def get_by_id(self, user_id: int) -> AppUser | None:
        """Return the account with this id, if one exists."""
        return self._session.get(AppUser, user_id)


class InviteRepository:
    """Create and inspect invites using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        """Bind repository methods to a session without taking transaction ownership."""
        self._session = session

    def create(
        self,
        league_id: int | None,
        code_hash: str,
        expires_at: datetime,
        role: str = ROLE_MEMBER,
    ) -> Invite:
        """Create an invite from an already-hashed code.

        ``league_id`` is ``None`` for an admin invite that is not tied to a league; callers that
        mint member invites pass the league. The caller owns code generation, hashing, and the
        seven-day default expiry; this method only persists the hash so the raw code is never
        stored here.
        """
        invite = Invite(
            league_id=league_id,
            code_hash=code_hash,
            expires_at=expires_at,
            role=role,
        )
        self._session.add(invite)
        self._session.flush()
        return invite

    def get_by_code_hash(self, code_hash: str) -> Invite | None:
        """Return the invite row with this hash, if one exists (expired rows included)."""
        return self._session.scalar(select(Invite).where(Invite.code_hash == code_hash))

    def is_valid(self, invite: Invite, *, now: datetime | None = None) -> bool:
        """Report whether an invite has not expired at ``now`` (default: current UTC time).

        An invite is valid strictly before ``expires_at``; at the expiry instant it is already
        invalid. Naive datetimes are interpreted as UTC, which keeps the SQLite round trip (which
        drops the offset) consistent with Postgres.
        """
        current = datetime.now(UTC) if now is None else now
        return _as_utc(current) < _as_utc(invite.expires_at)


class MembershipRepository:
    """Create and update user-league memberships using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        """Bind repository methods to a session without taking transaction ownership."""
        self._session = session

    def create(self, user_id: int, league_id: int, owner_id: int | None = None) -> UserLeague:
        """Create a membership for a user in a league.

        Raises :class:`DuplicateMembershipError` when the (user, league) pair already exists.
        Owner-league consistency is enforced by the service that calls this repository.
        """
        membership = UserLeague(user_id=user_id, league_id=league_id, owner_id=owner_id)
        self._session.add(membership)
        try:
            self._session.flush()
        except IntegrityError as error:
            if _is_unique_violation(error, _USER_LEAGUE_CONSTRAINTS):
                raise DuplicateMembershipError("user already belongs to this league") from None
            raise
        return membership

    def get(self, user_id: int, league_id: int) -> UserLeague | None:
        """Return the membership for this user and league, if one exists."""
        return self._session.scalar(
            select(UserLeague).where(
                UserLeague.user_id == user_id, UserLeague.league_id == league_id
            )
        )

    def list_for_user(self, user_id: int) -> list[UserLeague]:
        """Return a user's memberships ordered by league id."""
        return list(
            self._session.scalars(
                select(UserLeague)
                .where(UserLeague.user_id == user_id)
                .order_by(UserLeague.league_id)
            )
        )

    def list_for_league(self, league_id: int) -> list[UserLeague]:
        """Return a league's memberships ordered by user id."""
        return list(
            self._session.scalars(
                select(UserLeague)
                .where(UserLeague.league_id == league_id)
                .order_by(UserLeague.user_id)
            )
        )

    def set_owner(self, user_id: int, league_id: int, owner_id: int | None) -> UserLeague:
        """Set or clear the owner association on a membership.

        The caller is responsible for ensuring ``owner_id`` belongs to the membership's league.
        """
        membership = self._require(user_id, league_id)
        membership.owner_id = owner_id
        self._session.flush()
        return membership

    def set_credentials(
        self,
        user_id: int,
        league_id: int,
        *,
        espn_s2_encrypted: str,
        espn_swid_encrypted: str,
    ) -> UserLeague:
        """Store already-encrypted ESPN credential tokens on a membership.

        Values are opaque to this repository: it neither decrypts nor inspects them and never
        writes them to logs or error messages.
        """
        membership = self._require(user_id, league_id)
        membership.espn_s2_encrypted = espn_s2_encrypted
        membership.espn_swid_encrypted = espn_swid_encrypted
        self._session.flush()
        return membership

    def clear_credentials(self, user_id: int, league_id: int) -> UserLeague:
        """Remove both encrypted credential tokens from a membership."""
        membership = self._require(user_id, league_id)
        membership.espn_s2_encrypted = None
        membership.espn_swid_encrypted = None
        self._session.flush()
        return membership

    def _require(self, user_id: int, league_id: int) -> UserLeague:
        """Return a membership or raise :class:`MembershipNotFoundError`."""
        membership = self.get(user_id, league_id)
        if membership is None:
            raise MembershipNotFoundError("membership not found for this user and league")
        return membership
