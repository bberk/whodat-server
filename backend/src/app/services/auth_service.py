"""Invite-gated account creation and password authentication.

The service is transaction-neutral: every method flushes writes through a repository so generated
ids are usable, but never commits. The caller owns the transaction and calls
:meth:`AuthService.commit` (or rolls back) at the end of its unit of work; :meth:`signup` checks
for an existing email before inserting and rolls back only a concurrent duplicate that slips past
that check.

This module never logs passwords, password hashes, raw invite codes, or invite-code hashes, and its
error messages do not include them. League membership and credential handling deliberately live
elsewhere; signup only creates the account.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache

from sqlalchemy.orm import Session

from app.db.auth_repositories import (
    DuplicateEmailError as DatabaseDuplicateEmailError,
)
from app.db.auth_repositories import InviteRepository, UserRepository
from app.db.models import AppUser
from app.security.invite_codes import hash_invite_code, invite_code_matches
from app.security.passwords import hash_password, verify_password


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


class InactiveUserError(UserNotFoundError):
    """The account exists but must not authenticate.

    The current schema has no inactive flag, so every stored account is active; this typed error is
    reserved for when accounts can be deactivated. Callers already treat it as unauthenticated
    because it subclasses :class:`UserNotFoundError`.
    """


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
        self._clock = clock or _utc_now

    def commit(self) -> None:
        """Persist the caller's current unit of work.

        Service methods never commit on their own; this explicit boundary exists so callers do not
        need to reach into the session they injected.
        """
        self._session.commit()

    def signup(self, email: str, password: str, invite_code: str) -> AppUser:
        """Create an account from a valid invite and return it.

        The invite's role is copied onto the new account and the email is stored lowercase. Raises
        :class:`InviteError` for an unknown code, :class:`ExpiredInviteError` for an expired one,
        and :class:`EmailAlreadyRegisteredError` when the email is taken (case-insensitively). The
        caller commits. A duplicate is normally caught with a lookup before inserting; the unique
        constraint remains the authority for a concurrent signup, in which case the failed
        transaction is rolled back before the error is raised.
        """
        expected_hash = hash_invite_code(invite_code) if invite_code else ""
        invite = self._invites.get_by_code_hash(expected_hash) if expected_hash else None
        if invite is None or not invite_code_matches(invite_code, invite.code_hash):
            raise InviteError("invite code is invalid")
        if not self._invites.is_valid(invite, now=self._clock()):
            raise ExpiredInviteError("invite code has expired")
        if self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError("an account with this email already exists")

        password_hash = hash_password(password)
        try:
            return self._users.create(email, password_hash, role=invite.role)
        except DatabaseDuplicateEmailError:
            self._session.rollback()
            raise EmailAlreadyRegisteredError("an account with this email already exists") from None

    def authenticate(self, email: str, password: str) -> AppUser:
        """Return the account matching these credentials or raise :class:`InvalidCredentialsError`.

        Unknown emails still perform one Argon2id verification against a dummy hash so the failure
        takes approximately as long as a wrong password for a real account.
        """
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
        response. :class:`InactiveUserError` is the corresponding error once deactivation exists.
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user
