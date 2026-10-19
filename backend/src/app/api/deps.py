"""FastAPI dependencies shared by the auth routes.

The session factory is resolved through a dependency so tests can override it with a temporary
SQLite database without touching process settings. The router stays free of SQLAlchemy models: it
receives an :class:`~app.services.auth_service.AuthService` and public response schemas only.

The rate limiter is a process-wide singleton for the application; tests override
:func:`get_rate_limiter` with a limiter backed by a fake clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.rate_limit import RateLimiter, request_rate_limit_key
from app.api.schemas_auth import PublicUser, error_detail
from app.api.session import read_session_user_id
from app.db.session import get_session_factory as _default_session_factory
from app.services.auth_service import AuthService, UserNotFoundError

_NOT_AUTHENTICATED = error_detail("not_authenticated", "Authentication required")

_auth_rate_limiter = RateLimiter()


def get_db_session_factory() -> sessionmaker[Session]:
    """Return the application's session factory; override this to point tests at SQLite."""
    return _default_session_factory()


def get_db_session(
    factory: Annotated[sessionmaker[Session], Depends(get_db_session_factory)],
) -> Iterator[Session]:
    """Yield a request-scoped session and close it (rolling back uncommitted work) at the end."""
    with factory() as session:
        yield session


def get_auth_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthService:
    """Build the auth service for this request."""
    return AuthService(session)


def get_rate_limiter() -> RateLimiter:
    """Return the application-wide auth rate limiter."""
    return _auth_rate_limiter


def enforce_auth_rate_limit(
    request: Request,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    """Reject the request with 429 and a ``Retry-After`` header when this client is over the limit.

    The key is the direct client address plus the request path, so signup and login have separate
    buckets.
    """
    decision = limiter.check(request_rate_limit_key(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail("rate_limited", "Too many requests"),
            headers={"Retry-After": str(decision.retry_after)},
        )


def get_current_user(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PublicUser:
    """Return the signed-in user, or raise 401 for a missing, invalid, or stale session.

    A cookie can outlive its account, so ``UserNotFoundError`` (including its inactive-account
    subclass) is treated as unauthenticated rather than as a server error.
    """
    user_id = read_session_user_id(request)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_NOT_AUTHENTICATED,
        )
    try:
        user = service.get_active_user(user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_NOT_AUTHENTICATED,
        ) from None
    return PublicUser(id=user.id, email=user.email, role=user.role)
