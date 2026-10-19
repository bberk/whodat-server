"""Signed, stateless session cookies built from the standard library only.

Cookie format (``whodat_session=v1.<user_id>.<issued_at>.<signature>``):

* ``v1`` is the token version.
* ``user_id`` is the account id.
* ``issued_at`` is the Unix timestamp (seconds) at which the cookie was minted.
* ``signature`` is ``base64url(HMAC-SHA256(SECRET_KEY, "v1.<user_id>.<issued_at>"))`` without
  padding.

The cookie is valid while its age is strictly less than seven days (``SESSION_MAX_AGE_SECONDS``).
Verification is constant-time. A tampered, malformed, expired, or future-dated cookie is treated as
unauthenticated by returning ``None``; this module never raises for untrusted cookie input.

The cookie is ``httpOnly``, ``SameSite=Lax``, scoped to ``/``, and marked ``Secure`` whenever
``ENV`` is anything other than ``local``. It carries no password, invite code, or other secret and
is never logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import Request, Response

from app.config import get_settings

#: Name of the session cookie. Change it here if the cookie has to be renamed.
SESSION_COOKIE_NAME = "whodat_session"

#: Seven days, matching the documented invite/session lifetime.
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

#: Tolerance for a cookie minted on another host whose clock is slightly ahead.
SESSION_CLOCK_SKEW_SECONDS = 60

_TOKEN_VERSION = "v1"
_COOKIE_PATH = "/"


def set_session(response: Response, user_id: int, *, now: int | None = None) -> None:
    """Attach a freshly signed session cookie for ``user_id`` to ``response``.

    ``now`` exists for deterministic tests; production callers omit it and use the wall clock.
    """
    issued_at = int(time.time()) if now is None else now
    payload = f"{_TOKEN_VERSION}.{user_id}.{issued_at}"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=f"{payload}.{_sign(payload)}",
        max_age=SESSION_MAX_AGE_SECONDS,
        path=_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )


def clear_session(response: Response) -> None:
    """Expire the session cookie on ``response`` using the same scope and attributes."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )


def read_session_user_id(request: Request, *, now: int | None = None) -> int | None:
    """Return the signed-in user id, or ``None`` for any missing or invalid cookie.

    Expired cookies (age at least :data:`SESSION_MAX_AGE_SECONDS`), tokens minted too far in the
    future, unknown versions, malformed numbers, and bad signatures all read as unauthenticated.
    """
    value = request.cookies.get(SESSION_COOKIE_NAME)
    if not value:
        return None

    parts = value.split(".")
    if len(parts) != 4:
        return None
    version, raw_user_id, raw_issued_at, signature = parts
    if version != _TOKEN_VERSION:
        return None

    payload = f"{version}.{raw_user_id}.{raw_issued_at}"
    expected = _sign(payload).encode("ascii")
    if not hmac.compare_digest(expected, signature.encode("utf-8")):
        return None

    try:
        user_id = int(raw_user_id)
        issued_at = int(raw_issued_at)
    except ValueError:
        return None
    if user_id <= 0:
        return None

    current = int(time.time()) if now is None else now
    if issued_at > current + SESSION_CLOCK_SKEW_SECONDS:
        return None
    if current - issued_at >= SESSION_MAX_AGE_SECONDS:
        return None
    return user_id


def _sign(payload: str) -> str:
    """Return the base64url-encoded HMAC-SHA256 of ``payload`` under the configured secret."""
    key = get_settings().secret_key.encode("utf-8")
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _secure_cookies() -> bool:
    """Return whether cookies must carry the ``Secure`` attribute (every non-local environment)."""
    return get_settings().env.strip().lower() != "local"
