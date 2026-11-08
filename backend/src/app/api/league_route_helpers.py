"""Helper functions and HTTP error mapping for league API routes."""

from typing import Never

from fastapi import HTTPException, status

from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_leagues import (
    LeagueMemberSummary,
    LeagueSummary,
    OwnerSummary,
)
from app.services.league_exceptions import (
    AdminRequiredError,
    AlreadyMemberError,
    CredentialsRequiredError,
    DuplicateSeasonError,
    IncompleteCredentialsError,
    InvalidCupWeekError,
    InvalidInviteRequestError,
    InvalidLeagueRequestError,
    InvalidSeasonSettingsError,
    InviteNotRedeemableError,
    LastAdminError,
    LeagueAccessError,
    LeagueMemberNotFoundError,
    LeagueProviderError,
    LeagueSeasonNotFoundError,
    LeagueServiceError,
    LeagueSyncError,
    NotAMemberError,
    OwnerNotFoundError,
    RefreshRateLimitedError,
)
from app.services.league_models import (
    LeagueMemberView,
    LeagueUser,
    MembershipView,
    OwnerView,
)


def actor(user: PublicUser) -> LeagueUser:
    """Translate the public session identity into the service's caller type."""
    return LeagueUser(user_id=user.id, role=user.role)


def league_summary(view: MembershipView) -> LeagueSummary:
    """Project a service membership view into the public schema."""
    return LeagueSummary(
        league_id=view.league_id,
        provider=view.provider,
        external_id=view.external_id,
        name=view.name,
        owner_id=view.owner_id,
        has_credentials=view.has_credentials,
        show_wapdate=view.show_wapdate,
        has_trades_enabled=view.has_trades_enabled,
    )


def owner_summary(view: OwnerView) -> OwnerSummary:
    """Project a service owner view into the public schema."""
    return OwnerSummary(
        id=view.id,
        external_id=view.external_id,
        display_name=view.display_name,
    )


def member_summary(view: LeagueMemberView) -> LeagueMemberSummary:
    """Project a service member view into the public schema (no credential material)."""
    return LeagueMemberSummary(
        user_id=view.user_id,
        email=view.email,
        role=view.role,
        owner_id=view.owner_id,
        owner_name=view.owner_name,
        has_credentials=view.has_credentials,
    )


def http_error(error: LeagueServiceError) -> HTTPException:
    """Map a typed service failure to a structured HTTP response.

    No branch includes a credential, hash, or provider exception message in its body.
    """
    if isinstance(error, RefreshRateLimitedError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail("rate_limited", "League refresh is rate limited"),
            headers={"Retry-After": str(error.retry_after)},
        )
    if isinstance(error, AdminRequiredError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("forbidden", "Only an admin may perform this action"),
        )
    if isinstance(error, InvalidCupWeekError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                "invalid_cup_week",
                "cup_week must be between 1 and the season's regular season length",
            ),
        )
    if isinstance(error, InvalidInviteRequestError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("invalid_invite", "The invite request is not valid"),
        )
    if isinstance(error, LastAdminError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("last_admin", "A league must keep at least one admin member"),
        )
    if isinstance(error, InvalidSeasonSettingsError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("invalid_season_settings", "The season settings are not usable"),
        )
    if isinstance(error, InviteNotRedeemableError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("invalid_invite", "Invite code is invalid or expired"),
        )
    if isinstance(error, CredentialsRequiredError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("credentials_required", "This membership holds no credentials"),
        )
    if isinstance(error, (NotAMemberError, OwnerNotFoundError, LeagueMemberNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("not_found", "League or owner not found"),
        )
    if isinstance(error, LeagueSeasonNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("not_found", "League season not found"),
        )
    if isinstance(error, AlreadyMemberError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("already_member", "You already belong to this league"),
        )
    if isinstance(error, DuplicateSeasonError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("season_exists", "This season already exists for this league"),
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
    if isinstance(error, LeagueAccessError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                "league_unavailable",
                "The league could not be reached; private leagues require ESPN credentials",
            ),
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


def raise_http_error(error: LeagueServiceError) -> Never:
    """Raise the structured HTTP error for a service failure."""
    raise http_error(error) from None


# Backwards compatibility aliases
_actor = actor
_league_summary = league_summary
_owner_summary = owner_summary
_member_summary = member_summary
_http_error = http_error
_raise = raise_http_error
