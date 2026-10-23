"""Invite-gated account creation and password authentication.

The service is transaction-neutral: every method flushes writes through a repository so generated
ids are usable, but never commits. The caller owns the transaction and calls
:meth:`AuthService.commit` (or rolls back) at the end of its unit of work; :meth:`signup` checks
for an existing email before inserting and rolls back only a concurrent duplicate that slips past
that check.

A signup with a member invite also creates the invite's league membership in the same transaction
and returns a credential-free league reference. An admin invite is league-less and creates no
membership; the account completes onboarding by adding a league later. Credential handling stays in
the league service and provider layer.

This module never logs passwords, password hashes, raw invite codes, or invite-code hashes, and its
error messages do not include them.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.auth_repositories import (
    DuplicateEmailError as DatabaseDuplicateEmailError,
)
from app.db.auth_repositories import InviteRepository, MembershipRepository, UserRepository
from app.db.models import ROLE_ADMIN, ROLE_MEMBER, AppUser, UserLeague
from app.security.invite_codes import hash_invite_code, invite_code_matches
from app.security.passwords import hash_password, verify_password


@dataclass(frozen=True)
class LeagueReference:
    """A league a signup joined, with no membership or credential material."""

    league_id: int
    provider: str
    external_id: str
    name: str


@dataclass(frozen=True)
class SignupResult:
    """The created account and, for a member invite, the league membership it granted."""

    user: AppUser
    league: LeagueReference | None


class AuthServiceError(Exception):
    """Base class for expected authentication failures."""


class InviteError(AuthServiceError):
    """The submitted invite code is not valid (missing or unknown)."""


class ExpiredInviteError(InviteError):
    """The invite exists but its expiry instant has passed."""


class EmailAlreadyRegisteredError(AuthServiceError):
    """An account with this email already exists (comparison is case-insensitive)."""


class InvalidCredentialsError(AuthServiceError):
    """The email/password pair does not match an account.

    The same error is raised for an unknown email and a wrong password so callers cannot use it to
    enumerate accounts.
    """


class UserNotFoundError(AuthServiceError, LookupError):
    """No account exists for the requested user id."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"no account exists for user {user_id}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@cache
def _dummy_password_hash() -> str:
    """Return a throwaway Argon2id hash used to equalise unknown-email login timing.

    The password behind it is random and discarded; nothing verifies against it in practice.
    """
    return hash_password(secrets.token_urlsafe(32))


class AuthService:
    """Create accounts and authenticate users using a caller-owned session."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind the service to a session and an optional clock (used to judge invite expiry)."""
        self._session = session
        self._users = UserRepository(session)
        self._invites = InviteRepository(session)
        self._memberships = MembershipRepository(session)
        self._clock = clock or _utc_now

    def commit(self) -> None:
        """Persist the caller's current unit of work.

        Service methods never commit on their own; this explicit boundary exists so callers do not
        need to reach into the session they injected.
        """
        self._session.commit()

    def signup(self, email: str, password: str, invite_code: str) -> SignupResult:
        """Create an account from a valid invite and return it with any league it granted.

        The invite's role is copied onto the new account and the email is stored lowercase. A
        member invite creates the corresponding membership in the same transaction; an admin
        invite is league-less and creates none. Raises :class:`InviteError` for an unknown or
        malformed code (including a member invite without a league or an admin invite with one),
        :class:`ExpiredInviteError` for an expired one, and :class:`EmailAlreadyRegisteredError`
        when the email is taken (case-insensitively). The caller commits. A duplicate is normally
        caught with a lookup before inserting; the unique constraint remains the authority for a
        concurrent signup, in which case the failed transaction is rolled back before the error is
        raised.
        """
        expected_hash = hash_invite_code(invite_code) if invite_code else ""
        invite = self._invites.get_by_code_hash(expected_hash) if expected_hash else None
        if invite is None or not invite_code_matches(invite_code, invite.code_hash):
            raise InviteError("invite code is invalid")
        if not self._invites.is_valid(invite, now=self._clock()):
            raise ExpiredInviteError("invite code has expired")
        if invite.role == ROLE_MEMBER and invite.league_id is None:
            raise InviteError("invite code is invalid")
        if invite.role == ROLE_ADMIN and invite.league_id is not None:
            raise InviteError("invite code is invalid")
        if self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError("an account with this email already exists")

        password_hash = hash_password(password)
        try:
            user = self._users.create(email, password_hash, role=invite.role)
        except DatabaseDuplicateEmailError:
            self._session.rollback()
            raise EmailAlreadyRegisteredError("an account with this email already exists") from None

        league = None
        if invite.league_id is not None:
            membership = self._memberships.create(user.id, invite.league_id)
            league = self._league_reference(membership)
        return SignupResult(user=user, league=league)

    def user_has_league(self, user_id: int) -> bool:
        """Return whether the user holds at least one league membership.

        The onboarding gate needs only existence, so this is one indexed lookup rather than a
        membership list (and never one query per league).
        """
        return (
            self._session.scalar(
                select(UserLeague.id).where(UserLeague.user_id == user_id).limit(1)
            )
            is not None
        )

    def authenticate(self, email: str, password: str) -> AppUser:
        """Return the account matching these credentials or raise :class:`InvalidCredentialsError`.

        Credentials are ASCII-only by product decision (no Unicode passphrases). A non-ASCII email
        or password is still rejected as invalid credentials, not a validation error, so the HTTP
        layer returns the same generic 401 as a wrong password. Unknown emails still perform one
        Argon2id verification against a dummy hash so the failure takes approximately as long as a
        wrong password for a real account.
        """
        if not email.isascii() or not password.isascii():
            verify_password(password, _dummy_password_hash())
            raise InvalidCredentialsError("invalid email or password")
        user = self._users.get_by_email(email)
        if user is None:
            verify_password(password, _dummy_password_hash())
            raise InvalidCredentialsError("invalid email or password")
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("invalid email or password")
        return user

    def get_active_user(self, user_id: int) -> AppUser:
        """Return the account for ``user_id`` or raise :class:`UserNotFoundError`.

        Cookies can outlive an account, so callers translate this error into an unauthenticated
        response.
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def _league_reference(self, membership: UserLeague) -> LeagueReference:
        """Project the membership's league into a credential-free reference."""
        league = membership.league
        return LeagueReference(
            league_id=league.id,
            provider=league.provider,
            external_id=league.external_id,
            name=league.name,
        )
