"""Standings and VP-history routes (ARCHITECTURE.md section 8).

Both endpoints are cookie-authenticated and member-only. The auth dependency returns 401 for a
missing or invalid session, and the reused league membership check returns 404 for a non-member so
the response never confirms that a league exists. Unknown leagues and seasons are structured 404s;
stored data that cannot produce standings is a structured 400, never a 500 that leaks an exception
or an internal id.
"""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes_leagues import _actor, _http_error, get_league_service
from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_standings import (
    StandingsResponse,
    VpHistoryResponse,
    to_standings_response,
    to_vp_history_response,
)
from app.db.session import get_session
from app.services.league_service import LeagueService, LeagueServiceError
from app.services.standings_service import (
    LeagueNotFoundError,
    SeasonNotFoundError,
    StandingsService,
    StandingsServiceError,
    VpHistory,
)

router = APIRouter(prefix="/api/v1", tags=["standings"])

CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]
LeagueServiceDep = Annotated[LeagueService, Depends(get_league_service)]


def get_standings_service(
    session: Annotated[Session, Depends(get_session)],
) -> StandingsService:
    """Build the read-only standings service on the request's shared session."""
    return StandingsService(session)


StandingsServiceDep = Annotated[StandingsService, Depends(get_standings_service)]


def require_league_member(
    league_id: int,
    current_user: CurrentUserDep,
    league_service: LeagueServiceDep,
) -> None:
    """Reject non-members with the same structured 404 the league routes use.

    Authentication runs first, so an unauthenticated caller always receives 401 even when the
    league is unknown.
    """
    try:
        league_service.require_membership(_actor(current_user), league_id)
    except LeagueServiceError as error:
        raise _http_error(error) from None


MemberDep = Annotated[None, Depends(require_league_member)]


def _raise_standings_error(error: StandingsServiceError) -> Never:
    """Map a typed standings failure to a structured response without internal detail."""
    if isinstance(error, (LeagueNotFoundError, SeasonNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("not_found", "League or season not found"),
        ) from None
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail("standings_unavailable", "Standings are unavailable for this season"),
    ) from None


def _bounded_history(history: VpHistory, last_week: int | None) -> VpHistory:
    """Reject a week past the completed data and otherwise leave the history unchanged.

    The response projection performs the truncation; this check only decides whether the
    requested week refers to a completed week at all.
    """
    if last_week is not None and (not history.weeks or last_week > history.weeks[-1]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("week_out_of_range", "The week is outside the completed weeks"),
        )
    return history


@router.get(
    "/leagues/{league_id}/seasons/{season}/standings",
    response_model=StandingsResponse,
)
def get_standings(
    league_id: int,
    season: int,
    _member: MemberDep,
    service: StandingsServiceDep,
) -> StandingsResponse:
    """Return overall standings plus divisions that keep each team's overall league rank."""
    try:
        standings = service.get_standings(league_id, season)
    except StandingsServiceError as error:
        _raise_standings_error(error)
    return to_standings_response(standings)


@router.get(
    "/leagues/{league_id}/seasons/{season}/vp-history",
    response_model=VpHistoryResponse,
)
def get_vp_history(
    league_id: int,
    season: int,
    _member: MemberDep,
    service: StandingsServiceDep,
    week: Annotated[
        int | None,
        Query(ge=1, description="Limit the series to counted weeks up to this week."),
    ] = None,
) -> VpHistoryResponse:
    """Return counted weeks and each team's weekly and cumulative VP series.

    An optional ``week`` truncates every series at that week. A week beyond the completed data is
    a structured 400 rather than an empty or partial chart.
    """
    try:
        history = _bounded_history(service.get_vp_history(league_id, season), week)
    except StandingsServiceError as error:
        _raise_standings_error(error)
    return to_vp_history_response(history, last_week=week)
