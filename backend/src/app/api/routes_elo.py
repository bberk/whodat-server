"""Elo history and per-league Elo settings routes (ARCHITECTURE.md section 8).

History is member-only: unauthenticated requests get 401 and non-members or unknown leagues get a
structured 404, matching the standings routes. Settings are admin-only: a non-admin member gets
403 and a non-member gets 404. Responses contain exact decimal strings and never any credential,
token, or provider exception text.
"""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.params import LeagueIdPath
from app.api.routes_leagues import _actor, _http_error
from app.api.routes_standings import MemberDep
from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_elo import (
    EloConfigResponse,
    EloConfigUpdateRequest,
    EloHistoryResponse,
    to_config_response,
    to_history_response,
)
from app.db.session import get_session
from app.domain.elo import EloMode
from app.services.elo_service import EloLeagueNotFoundError, EloService, InvalidEloConfigError
from app.services.league_service import LeagueServiceError

router = APIRouter(prefix="/api/v1", tags=["elo"])

CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]
ModeQuery = Annotated[
    EloMode,
    Query(description="Rating model: actual stored matchups, or every team compared each week"),
]


def get_elo_service(
    session: Annotated[Session, Depends(get_session)],
) -> EloService:
    """Build the read/settings service on the request's shared session."""
    return EloService(session)


EloServiceDep = Annotated[EloService, Depends(get_elo_service)]


def _raise_history_error(error: EloLeagueNotFoundError) -> Never:
    """Map an unknown league to a structured 404 without internal detail."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail("not_found", "League not found"),
    ) from None


def _raise_settings_error(error: InvalidEloConfigError) -> Never:
    """Map service-level settings validation to a structured 400."""
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail(
            "invalid_elo_config",
            "Elo settings are outside the allowed ranges",
        ),
    ) from None


@router.get(
    "/leagues/{league_id}/elo-history",
    response_model=EloHistoryResponse,
)
def get_elo_history(
    league_id: LeagueIdPath,
    _member: MemberDep,
    service: EloServiceDep,
    mode: ModeQuery = "round_robin",
) -> EloHistoryResponse:
    """Return full running Elo history for a league in the requested mode."""
    try:
        history = service.get_history(league_id, mode)
    except EloLeagueNotFoundError as error:
        _raise_history_error(error)
    return to_history_response(history)


@router.get(
    "/leagues/{league_id}/elo-config",
    response_model=EloConfigResponse,
)
def get_elo_config(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: EloServiceDep,
) -> EloConfigResponse:
    """Return a league's saved Elo settings, or the defaults, for an admin member.

    A non-member gets 404 (the league is not confirmed to exist) and a member without the admin
    role gets 403.
    """
    try:
        config = service.get_config(_actor(current_user), league_id)
    except LeagueServiceError as error:
        raise _http_error(error) from None
    return to_config_response(league_id, config)


@router.put(
    "/leagues/{league_id}/elo-config",
    response_model=EloConfigResponse,
)
def update_elo_config(
    league_id: LeagueIdPath,
    payload: EloConfigUpdateRequest,
    current_user: CurrentUserDep,
    service: EloServiceDep,
) -> EloConfigResponse:
    """Validate and persist a league's Elo settings for an admin member."""
    try:
        config = service.update_config(
            _actor(current_user),
            league_id,
            starting_rating=payload.starting_rating,
            k_factor=payload.k_factor,
            margin_weight=payload.margin_weight,
            margin_cap=payload.margin_cap,
            season_regression=payload.season_regression,
        )
        service.commit()
    except LeagueServiceError as error:
        raise _http_error(error) from None
    except InvalidEloConfigError as error:
        _raise_settings_error(error)
    return to_config_response(league_id, config)
