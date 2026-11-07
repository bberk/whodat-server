"""API endpoints for trade tracker settings, GitHub repo synchronization, and auction budgets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.league_route_helpers import actor, http_error
from app.api.params import LeagueIdPath
from app.api.refresh_limit import get_trade_sync_limiter
from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_trades import (
    AuctionBudgetsResponse,
    BudgetDeltaItem,
    TradeConfigResponse,
    TradeConfigUpdateRequest,
    TradeItem,
    TradePartyItem,
    TradesListResponse,
    TradeSyncResponse,
    to_team_budget_projection_item,
    to_trade_config_response,
    to_trade_sync_response,
)
from app.db.session import get_session
from app.services.league_exceptions import LeagueServiceError
from app.services.refresh_limiter import RefreshRateLimiter
from app.services.trade_sync_service import (
    TradeLedgerFormatError,
    TradeSyncGitHubError,
    TradeSyncRateLimitedError,
    TradeSyncService,
    TradeTrackerDisabledError,
)

router = APIRouter(prefix="/api/v1", tags=["trades"])

CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]


def get_trade_sync_service(
    session: Annotated[Session, Depends(get_session)],
    limiter: Annotated[RefreshRateLimiter, Depends(get_trade_sync_limiter)],
) -> TradeSyncService:
    """Build the TradeSyncService on the request's shared session."""
    return TradeSyncService(session, rate_limiter=limiter)


TradeSyncServiceDep = Annotated[TradeSyncService, Depends(get_trade_sync_service)]


def _trade_http_error(exc: Exception) -> HTTPException:
    """Map trade service exceptions to structured HTTP errors."""
    if isinstance(exc, LeagueServiceError):
        return http_error(exc)
    if isinstance(exc, TradeSyncRateLimitedError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail("rate_limited", str(exc)),
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, TradeTrackerDisabledError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("trade_tracker_disabled", str(exc)),
        )
    if isinstance(exc, (TradeSyncGitHubError, TradeLedgerFormatError)):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error_detail("github_sync_failed", str(exc)),
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail("trade_request_failed", str(exc)),
    )


@router.get(
    "/leagues/{league_id}/trade-config",
    response_model=TradeConfigResponse,
)
def get_trade_config(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: TradeSyncServiceDep,
) -> TradeConfigResponse:
    """Return a league's trade tracker settings for an admin member."""
    try:
        view = service.get_config(actor(current_user), league_id)
    except Exception as exc:
        raise _trade_http_error(exc) from None
    return to_trade_config_response(view)


@router.put(
    "/leagues/{league_id}/trade-config",
    response_model=TradeConfigResponse,
)
def update_trade_config(
    league_id: LeagueIdPath,
    payload: TradeConfigUpdateRequest,
    current_user: CurrentUserDep,
    service: TradeSyncServiceDep,
) -> TradeConfigResponse:
    """Update a league's trade tracker settings for an admin member."""
    try:
        view = service.update_config(
            actor(current_user),
            league_id,
            enabled=payload.enabled,
            discord_channel_id=payload.discord_channel_id,
            repo_owner=payload.repo_owner,
            repo_name=payload.repo_name,
            branch=payload.branch,
            github_token=payload.github_token,
            clear_github_token=payload.clear_github_token,
            base_auction_budget=payload.base_auction_budget,
            team_aliases=payload.team_aliases,
        )
        service.commit()
    except Exception as exc:
        raise _trade_http_error(exc) from None
    return to_trade_config_response(view)


@router.post(
    "/leagues/{league_id}/trades/sync",
    response_model=TradeSyncResponse,
)
def sync_trade_repo(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: TradeSyncServiceDep,
) -> TradeSyncResponse:
    """Trigger a sync of the trade ledger from the configured GitHub repository."""
    try:
        result = service.sync_trade_repo(actor(current_user), league_id)
        service.commit()
    except Exception as exc:
        raise _trade_http_error(exc) from None
    return to_trade_sync_response(result)


@router.get(
    "/leagues/{league_id}/trades",
    response_model=TradesListResponse,
)
def list_trades(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: TradeSyncServiceDep,
    draft_year: Annotated[int | None, Query(description="Filter by draft year")] = None,
    team: Annotated[str | None, Query(description="Filter by team name")] = None,
) -> TradesListResponse:
    """Return all ingested trades for a league, optionally filtered by draft year or team."""
    try:
        trades = service.list_trades(
            actor(current_user), league_id, draft_year=draft_year, team_name=team
        )
    except Exception as exc:
        raise _trade_http_error(exc) from None

    trade_items: list[TradeItem] = []
    for t in trades:
        parties: list[TradePartyItem] = []
        for p in t.parties:
            deltas = [
                BudgetDeltaItem(draft_year=d.draft_year, amount=f"{d.amount:.2f}")
                for d in p.budget_deltas
            ]
            parties.append(
                TradePartyItem(
                    id=p.id,
                    owner_id=p.owner_id,
                    franchise_key=p.franchise_key,
                    team_name_raw=p.team_name_raw,
                    players_sent=p.players_sent,
                    players_received=p.players_received,
                    draft_picks_sent=p.draft_picks_sent,
                    draft_picks_received=p.draft_picks_received,
                    auction_dollars=deltas,
                )
            )
        trade_items.append(
            TradeItem(
                id=t.id,
                external_trade_id=t.external_trade_id,
                trade_date=t.trade_date,
                agreement_season=t.agreement_season,
                is_settled=t.is_settled,
                discord_url=t.discord_url,
                summary=t.summary,
                conditions=t.conditions,
                parties=parties,
            )
        )

    return TradesListResponse(league_id=league_id, trades=trade_items)


@router.get(
    "/leagues/{league_id}/auction-budgets",
    response_model=AuctionBudgetsResponse,
)
def get_auction_budgets(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    service: TradeSyncServiceDep,
    draft_year: Annotated[int, Query(description="Target draft year to project")],
) -> AuctionBudgetsResponse:
    """Calculate and return projected auction budgets for all league teams."""
    try:
        projections = service.get_auction_budgets(
            actor(current_user), league_id, target_draft_year=draft_year
        )
        config = service.get_or_create_config(league_id)
    except Exception as exc:
        raise _trade_http_error(exc) from None

    return AuctionBudgetsResponse(
        league_id=league_id,
        draft_year=draft_year,
        base_auction_budget=f"{config.base_auction_budget:.2f}",
        projections=[to_team_budget_projection_item(p) for p in projections],
    )
