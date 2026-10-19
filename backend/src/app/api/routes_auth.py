"""Account authentication routes (ARCHITECTURE.md section 8).

``POST /api/v1/auth/signup`` creates an invite-gated account, ``POST /api/v1/auth/login`` starts a
session, ``POST /api/v1/auth/logout`` clears it, and ``GET /api/v1/me`` returns the signed-in user.
Signup and login are rate limited; all responses are JSON and never include password hashes,
invite codes, credentials, or tracebacks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import enforce_auth_rate_limit, get_auth_service, get_current_user
from app.api.schemas_auth import (
    LoginRequest,
    LogoutResponse,
    PublicUser,
    SignupRequest,
    error_detail,
)
from app.api.session import clear_session, set_session
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InviteError,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
RateLimitDep = Annotated[None, Depends(enforce_auth_rate_limit)]
CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]

_INVALID_INVITE = error_detail("invalid_invite", "Invite code is invalid or expired")
_EMAIL_TAKEN = error_detail("email_taken", "An account with this email already exists")
_INVALID_CREDENTIALS = error_detail("invalid_credentials", "Invalid email or password")


@router.post(
    "/auth/signup",
    response_model=PublicUser,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: SignupRequest,
    response: Response,
    _rate_limit: RateLimitDep,
    service: AuthServiceDep,
) -> PublicUser:
    """Create an account from a valid invite, set the session cookie, and return the public user.

    Unknown and expired invite codes share one 400 response so the endpoint does not help a caller
    distinguish which part failed. A taken email returns 409.
    """
    try:
        user = service.signup(
            payload.email,
            payload.password.get_secret_value(),
            payload.invite_code.get_secret_value(),
        )
        service.commit()
    except InviteError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_INVITE,
        ) from None
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_EMAIL_TAKEN,
        ) from None

    set_session(response, user.id)
    return PublicUser(id=user.id, email=user.email, role=user.role)


@router.post("/auth/login", response_model=PublicUser)
def login(
    payload: LoginRequest,
    response: Response,
    _rate_limit: RateLimitDep,
    service: AuthServiceDep,
) -> PublicUser:
    """Verify credentials, set the session cookie, and return the public user.

    An unknown email and a wrong password return the same 401 body, so the endpoint cannot be used
    to enumerate accounts.
    """
    try:
        user = service.authenticate(payload.email, payload.password.get_secret_value())
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS,
        ) from None

    set_session(response, user.id)
    return PublicUser(id=user.id, email=user.email, role=user.role)


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(response: Response) -> LogoutResponse:
    """Clear the session cookie.

    Logout is idempotent: it succeeds even when the caller has no valid session, so a browser can
    always discard a stale or tampered cookie.
    """
    clear_session(response)
    return LogoutResponse(status="ok")


@router.get("/me", response_model=PublicUser)
def me(current_user: CurrentUserDep) -> PublicUser:
    """Return the account tied to the session cookie, or 401 when unauthenticated."""
    return current_user
