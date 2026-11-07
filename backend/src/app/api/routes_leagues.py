"""League membership, owner, seasons, season-add, and refresh routes (ARCHITECTURE.md section 8).

All routes are cookie-authenticated and league-scoped operations enforce membership in the
service. Non-members receive 404 so the response does not confirm that a league exists;
unauthenticated requests are rejected with 401 by the auth dependency. Credential values are never
accepted into a response, logged, or included in an error message.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.league_route_helpers import (
    _actor,
    _http_error,
    _league_summary,
    _member_summary,
    _owner_summary,
    _raise,
)
from app.api.params import LeagueIdPath, MemberUserIdPath, SeasonPath
from app.api.refresh_limit import get_refresh_limiter, get_season_refresh_limiter
from app.api.schemas_auth import PublicUser
from app.api.schemas_leagues import (
    AddLeagueRequest,
    AddLeagueResponse,
    AddSeasonRequest,
    AddSeasonResponse,
    CreateInviteRequest,
    CreateInviteResponse,
    CupWeekResponse,
    CupWeekUpdateRequest,
    DisplaySettingsUpdateRequest,
    LeagueMembersResponse,
    LeagueSummary,
    OwnersResponse,
    OwnerUpdateRequest,
    OwnerUpdateResponse,
    RedeemInviteRequest,
    RedeemInviteResponse,
    RefreshResponse,
    SeasonRefreshResponse,
    SeasonSettingsResponse,
    SeasonSettingsSummary,
    SeasonsResponse,
)
from app.db.session import get_session
from app.providers.espn.credentials import create_espn_provider
from app.services.league_service import (
    EspnCredentials,
    LeagueService,
    LeagueServiceError,
)

__all__ = [
    "_actor",
    "_http_error",
    "_league_summary",
    "_member_summary",
    "_owner_summary",
    "_raise",
    "get_league_service",
    "router",
]

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
        season_refresh_limiter=get_season_refresh_limiter(),
    )


ServiceDep = Annotated[LeagueService, Depends(get_league_service)]


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
    """Add a league as an admin; members join only by redeeming a member invite."""
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


@router.post(
    "/me/leagues/redeem-invite",
    response_model=RedeemInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
def redeem_invite(
    payload: RedeemInviteRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> RedeemInviteResponse:
    """Join the league named by a valid member invite, creating exactly one membership.

    Unknown, expired, admin-role, and league-less invites share one structured 400 so the endpoint
    does not reveal which part failed; a duplicate membership returns 409. The submitted code is
    never echoed in the response or an error message.
    """
    try:
        membership = service.redeem_invite(
            _actor(current_user),
            payload.invite_code.get_secret_value(),
        )
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return RedeemInviteResponse(league=_league_summary(membership))


@router.get("/me/leagues", response_model=list[LeagueSummary])
def list_my_leagues(
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> list[LeagueSummary]:
    """Return the leagues the signed-in user belongs to."""
    return [_league_summary(view) for view in service.list_memberships(_actor(current_user))]


@router.get("/leagues/{league_id}/seasons", response_model=SeasonsResponse)
def list_league_seasons(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> SeasonsResponse:
    """Return the seasons stored for a league the caller belongs to."""
    try:
        seasons = service.list_seasons(_actor(current_user), league_id)
    except LeagueServiceError as error:
        _raise(error)
    return SeasonsResponse(seasons=seasons)


@router.get(
    "/leagues/{league_id}/seasons/settings",
    response_model=SeasonSettingsResponse,
)
def list_league_season_settings(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> SeasonSettingsResponse:
    """Return every stored season's admin settings for an admin member.

    A non-member gets 404 (the league is not confirmed to exist) and a member without the admin
    role gets 403. The cup week, regular-season week range, and last successful provider sync are
    read from stored rows; no provider is contacted.
    """
    try:
        settings = service.list_season_settings(_actor(current_user), league_id)
    except LeagueServiceError as error:
        _raise(error)
    return SeasonSettingsResponse(
        seasons=[
            SeasonSettingsSummary(
                season=view.season,
                cup_week=view.cup_week,
                regular_season_length=view.regular_season_length,
                last_refreshed_at=view.last_refreshed_at,
            )
            for view in settings
        ]
    )


@router.post(
    "/leagues/{league_id}/seasons",
    response_model=AddSeasonResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_league_season(
    league_id: LeagueIdPath,
    payload: AddSeasonRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> AddSeasonResponse:
    """Add and sync one more season for an existing league.

    Only a global admin who belongs to the league may call this. The season sync uses the caller's
    own stored credentials, and the whole write is atomic: a provider failure returns a structured
    error and leaves no partial season behind. Credential values never appear in the response.
    """
    try:
        result = service.add_season(_actor(current_user), league_id, payload.season)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return AddSeasonResponse(
        league_id=result.league_id,
        season=result.season,
        weeks_synced=list(result.weeks_synced),
    )


@router.post(
    "/leagues/{league_id}/seasons/{season}/refresh",
    response_model=SeasonRefreshResponse,
)
def refresh_league_season(
    league_id: LeagueIdPath,
    season: SeasonPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> SeasonRefreshResponse:
    """Refresh one stored season through the provider with the caller's stored credentials.

    The season must already exist, so a refresh never creates or duplicates a season. Rate limits,
    credential requirements, and structured errors match the league-wide refresh.
    """
    try:
        result = service.refresh_season(_actor(current_user), league_id, season)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return SeasonRefreshResponse(
        season=result.season,
        weeks_synced=list(result.weeks_synced),
    )


@router.delete(
    "/leagues/{league_id}/seasons/{season}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_league_season(
    league_id: LeagueIdPath,
    season: SeasonPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> Response:
    """Delete one stored season's data, keeping the league, accounts, and other seasons.

    Scores, matchups, teams, and the season row go in one transaction; owners, memberships,
    invites, the league, and every other season remain. An unknown or unreadable season returns a
    structured 404.
    """
    try:
        service.delete_season(_actor(current_user), league_id, season)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/leagues/{league_id}/seasons/{season}/cup-week", response_model=CupWeekResponse)
def get_cup_week(
    league_id: LeagueIdPath,
    season: SeasonPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> CupWeekResponse:
    """Return a stored season's cup week and the regular-season week range it may use."""
    try:
        view = service.get_cup_week(_actor(current_user), league_id, season)
    except LeagueServiceError as error:
        _raise(error)
    return CupWeekResponse(
        season=view.season,
        cup_week=view.cup_week,
        regular_season_length=view.regular_season_length,
    )


@router.put("/leagues/{league_id}/seasons/{season}/cup-week", response_model=CupWeekResponse)
def update_cup_week(
    league_id: LeagueIdPath,
    season: SeasonPath,
    payload: CupWeekUpdateRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> CupWeekResponse:
    """Set or clear a season's cup week and recompute its stored VP in the same transaction."""
    try:
        view = service.set_cup_week(_actor(current_user), league_id, season, payload.cup_week)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return CupWeekResponse(
        season=view.season,
        cup_week=view.cup_week,
        regular_season_length=view.regular_season_length,
    )


@router.get("/leagues/{league_id}/owners", response_model=OwnersResponse)
def list_league_owners(
    league_id: LeagueIdPath,
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
    league_id: LeagueIdPath,
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


@router.put("/leagues/{league_id}/display-settings", response_model=LeagueSummary)
def update_display_settings(
    league_id: LeagueIdPath,
    payload: DisplaySettingsUpdateRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> LeagueSummary:
    """Set whether this league's standings page shows the WAPDate section.

    Only an admin member may change it: a non-member gets 404 (the league is not confirmed to
    exist) and a member without the admin role gets 403. The flag is per league and display-only,
    so no stored scores, VP, or rankings change; the updated league summary is returned so the
    client can replace its cached league and drop or restore the section immediately.
    """
    try:
        membership = service.update_display_settings(
            _actor(current_user),
            league_id,
            show_wapdate=payload.show_wapdate,
        )
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return _league_summary(membership)


@router.post("/leagues/{league_id}/refresh", response_model=RefreshResponse)
def refresh_league(
    league_id: LeagueIdPath,
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


@router.get("/leagues/{league_id}/members", response_model=LeagueMembersResponse)
def list_league_members(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> LeagueMembersResponse:
    """List the accounts associated with a league for an admin member.

    A non-member gets 404 (the league is not confirmed to exist) and a member without the admin
    role gets 403. Emails are the account identifier; passwords, credentials, and hashes are never
    part of the response.
    """
    try:
        members = service.list_members(_actor(current_user), league_id)
    except LeagueServiceError as error:
        _raise(error)
    return LeagueMembersResponse(members=[_member_summary(view) for view in members])


@router.delete(
    "/leagues/{league_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_league_member(
    league_id: LeagueIdPath,
    member_user_id: MemberUserIdPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> Response:
    """Remove one user's membership in this league, subject to the last-admin guard.

    The account and its other memberships are untouched. Removing the last admin member returns a
    structured 409; a user without a membership in this league returns 404.
    """
    try:
        service.remove_member(_actor(current_user), league_id, member_user_id)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/leagues/{league_id}/invites",
    response_model=CreateInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_league_invite(
    league_id: LeagueIdPath,
    payload: CreateInviteRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> CreateInviteResponse:
    """Generate one invite from the admin page and return its raw code exactly once.

    A member invite is bound to this league; an admin invite is league-less. Only the code hash is
    stored, so no other endpoint can return the code again. Defaults to a seven-day expiry.
    """
    try:
        invite = service.create_invite(
            _actor(current_user),
            league_id,
            payload.role,
            payload.expires_in_days,
        )
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return CreateInviteResponse(
        code=invite.code,
        role=invite.role,
        league_id=invite.league_id,
        expires_at=invite.expires_at,
    )


@router.delete("/leagues/{league_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_league(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> Response:
    """Delete this league and all of its data, leaving accounts and other leagues intact."""
    try:
        service.delete_league(_actor(current_user), league_id)
        service.commit()
    except LeagueServiceError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
