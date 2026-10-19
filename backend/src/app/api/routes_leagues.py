"""League membership, owner, seasons, and refresh routes (ARCHITECTURE.md section 8).

All routes are cookie-authenticated and league-scoped operations enforce membership in the
service. Non-members receive 404 so the response does not confirm that a league exists;
unauthenticated requests are rejected with 401 by the auth dependency. Credential values are never
accepted into a response, logged, or included in an error message.
"""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.refresh_limit import get_refresh_limiter
from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_leagues import (
    AddLeagueRequest,
    AddLeagueResponse,
    LeagueSummary,
    OwnersResponse,
    OwnerSummary,
    OwnerUpdateRequest,
    OwnerUpdateResponse,
    RefreshResponse,
    SeasonsResponse,
)
from app.db.session import get_session
from app.providers.espn.credentials import create_espn_provider
from app.services.league_service import (
    AlreadyMemberError,
    CredentialPermissionError,
    CredentialsRequiredError,
    EspnCredentials,
    IncompleteCredentialsError,
    InvalidLeagueRequestError,
    LeagueNotFoundError,
    LeagueProviderError,
    LeagueService,
    LeagueServiceError,
    LeagueSyncError,
    LeagueUser,
    MembershipView,
    NotAMemberError,
    OwnerNotFoundError,
    OwnerView,
    RefreshRateLimitedError,
)

router = APIRouter(prefix="/api/v1", tags=["leagues"])

CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]


def get_league_service(
    session: Annotated[Session, Depends(get_session)],
) -> LeagueService:
    """Build the league service with the production credential-backed provider factory."""
    return LeagueService(
        session,
        create_espn_provider,
        refresh_limiter=get_refresh_limiter(),
    )


ServiceDep = Annotated[LeagueService, Depends(get_league_service)]


def _actor(user: PublicUser) -> LeagueUser:
    """Translate the public session identity into the service's caller type."""
    return LeagueUser(user_id=user.id, role=user.role)


def _league_summary(view: MembershipView) -> LeagueSummary:
    """Project a service membership view into the public schema."""
    return LeagueSummary(
        league_id=view.league_id,
        provider=view.provider,
        external_id=view.external_id,
        name=view.name,
        owner_id=view.owner_id,
        has_credentials=view.has_credentials,
    )


def _owner_summary(view: OwnerView) -> OwnerSummary:
    """Project a service owner view into the public schema."""
    return OwnerSummary(
        id=view.id,
        external_id=view.external_id,
        display_name=view.display_name,
    )


def _http_error(error: LeagueServiceError) -> HTTPException:
    """Map a typed service failure to a structured HTTP response.

    No branch includes a credential, hash, or provider exception message in its body.
    """
    if isinstance(error, RefreshRateLimitedError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail("rate_limited", "League refresh is rate limited"),
            headers={"Retry-After": str(error.retry_after)},
        )
    if isinstance(error, CredentialPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("forbidden", "Only an admin may add league credentials"),
        )
    if isinstance(error, CredentialsRequiredError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("credentials_required", "This membership holds no credentials"),
        )
    if isinstance(error, (NotAMemberError, LeagueNotFoundError, OwnerNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("not_found", "League or owner not found"),
        )
    if isinstance(error, AlreadyMemberError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("already_member", "You already belong to this league"),
        )
    if isinstance(error, IncompleteCredentialsError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("invalid_credentials", "Both ESPN cookies are required"),
        )
    if isinstance(error, InvalidLeagueRequestError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("invalid_request", "The league request is not valid"),
        )
    if isinstance(error, LeagueProviderError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("league_unavailable", "The league could not be reached"),
        )
    if isinstance(error, LeagueSyncError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("sync_failed", "The league could not be synced"),
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail("request_failed", "The league request could not be completed"),
    )


def _raise(error: LeagueServiceError) -> Never:
    """Raise the structured HTTP error for a service failure."""
    raise _http_error(error) from None


@router.post(
    "/leagues",
    response_model=AddLeagueResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_league(
    payload: AddLeagueRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> AddLeagueResponse:
    """Add a league with admin credentials or join an already-stored league as a member."""
    credentials = None
    if payload.espn_s2 is not None and payload.espn_swid is not None:
        credentials = EspnCredentials(
            espn_s2=payload.espn_s2.get_secret_value(),
            espn_swid=payload.espn_swid.get_secret_value(),
        )
    try:
        result = service.add_league(
            _actor(current_user),
            payload.espn_league_id,
            payload.season,
            credentials,
        )
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return AddLeagueResponse(
        league=_league_summary(result.membership),
        season=result.season,
        weeks_synced=list(result.weeks_synced),
    )


@router.get("/me/leagues", response_model=list[LeagueSummary])
def list_my_leagues(
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> list[LeagueSummary]:
    """Return the leagues the signed-in user belongs to."""
    return [_league_summary(view) for view in service.list_memberships(_actor(current_user))]


@router.get("/leagues/{league_id}/seasons", response_model=SeasonsResponse)
def list_league_seasons(
    league_id: int,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> SeasonsResponse:
    """Return the seasons stored for a league the caller belongs to."""
    try:
        seasons = service.list_seasons(_actor(current_user), league_id)
    except LeagueServiceError as error:
        _raise(error)
    return SeasonsResponse(seasons=seasons)


@router.get("/leagues/{league_id}/owners", response_model=OwnersResponse)
def list_league_owners(
    league_id: int,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> OwnersResponse:
    """Return the owners a member may associate with their own membership."""
    try:
        owners = service.list_owners(_actor(current_user), league_id)
    except LeagueServiceError as error:
        _raise(error)
    return OwnersResponse(owners=[_owner_summary(view) for view in owners])


@router.put("/me/leagues/{league_id}/owner", response_model=OwnerUpdateResponse)
def set_my_owner(
    league_id: int,
    payload: OwnerUpdateRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> OwnerUpdateResponse:
    """Set or clear the caller's own owner association within a league they belong to."""
    try:
        membership = service.set_owner(_actor(current_user), league_id, payload.owner_id)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return OwnerUpdateResponse(league=_league_summary(membership))


@router.post("/leagues/{league_id}/refresh", response_model=RefreshResponse)
def refresh_league(
    league_id: int,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> RefreshResponse:
    """Refresh a league using the caller's stored credentials, subject to rate limits."""
    try:
        result = service.refresh(_actor(current_user), league_id)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return RefreshResponse(
        league_id=result.league_id,
        season=result.season,
        weeks_synced=list(result.weeks_synced),
        weeks_with_vp_recomputed=list(result.weeks_with_vp_recomputed),
    )
