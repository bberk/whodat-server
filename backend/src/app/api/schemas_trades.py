"""Pydantic schemas for trade tracker settings, sync operations, and auction budget projections."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.trade_budget import TeamBudgetProjection
from app.services.trade_sync_service import (
    AuctionBudgetsView,
    DiscordSyncTriggerResult,
    TradeConfigView,
    TradeSyncResult,
    TradeView,
)


class TradeConfigResponse(BaseModel):
    """Public, credential-safe trade tracker configuration."""

    league_id: int
    enabled: bool
    discord_channel_id: str | None
    repo_owner: str
    repo_name: str
    branch: str
    has_github_token: bool
    base_auction_budget: str
    team_aliases: dict[str, Any]
    last_synced_at: datetime | None
    last_sync_commit: str | None
    last_sync_status: str
    last_sync_error: str | None
    last_discord_sync_at: datetime | None
    discord_sync_status: str
    last_discord_sync_error: str | None


class TradeConfigUpdateRequest(BaseModel):
    """Admin request body to update trade tracker configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    discord_channel_id: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    branch: str | None = None
    github_token: str | None = None
    clear_github_token: bool = False
    base_auction_budget: Decimal | None = Field(default=None, ge=Decimal("0.00"))
    team_aliases: dict[str, Any] | None = None


class TradeSyncResponse(BaseModel):
    """Response returned upon completing a trade repository sync."""

    league_id: int
    status: str
    trades_synced: int
    commit_sha: str | None
    synced_at: datetime


class TradeDiscordSyncResponse(BaseModel):
    """Response returned upon initiating a background Discord trade sync."""

    league_id: int
    status: str
    message: str


class BudgetDeltaItem(BaseModel):
    """One auction budget adjustment leg."""

    draft_year: int
    amount: str


class TradePartyItem(BaseModel):
    """One party involved in a trade."""

    id: int
    owner_id: int | None
    franchise_key: str | None
    team_name_raw: str
    players_sent: list[dict[str, Any]]
    players_received: list[dict[str, Any]]
    draft_picks_sent: list[dict[str, Any]]
    draft_picks_received: list[dict[str, Any]]
    auction_dollars: list[BudgetDeltaItem]


class TradeItem(BaseModel):
    """A recorded league trade."""

    id: int
    external_trade_id: str
    trade_date: datetime
    agreement_season: int
    is_settled: bool
    discord_url: str | None
    summary: str
    conditions: list[dict[str, Any]]
    parties: list[TradePartyItem]


class TradesListResponse(BaseModel):
    """List of all trades recorded for a league."""

    league_id: int
    trades: list[TradeItem]


class TeamBudgetProjectionItem(BaseModel):
    """Projected auction budget for a team in a target draft year."""

    team_id: str
    starting_budget: str
    base_trade_delta: str
    fulfilled_conditional_delta: str
    net_delta: str
    projected_budget: str
    pending_conditional_delta: str
    is_negative_budget: bool


class AuctionBudgetsResponse(BaseModel):
    """Summary table of projected auction budgets for a target draft year."""

    league_id: int
    draft_year: int
    base_auction_budget: str
    projections: list[TeamBudgetProjectionItem]


def to_trade_config_response(view: TradeConfigView) -> TradeConfigResponse:
    """Format a service config view into the public API response."""
    return TradeConfigResponse(
        league_id=view.league_id,
        enabled=view.enabled,
        discord_channel_id=view.discord_channel_id,
        repo_owner=view.repo_owner,
        repo_name=view.repo_name,
        branch=view.branch,
        has_github_token=view.has_github_token,
        base_auction_budget=f"{view.base_auction_budget:.2f}",
        team_aliases=view.team_aliases,
        last_synced_at=view.last_synced_at,
        last_sync_commit=view.last_sync_commit,
        last_sync_status=view.last_sync_status,
        last_sync_error=view.last_sync_error,
        last_discord_sync_at=view.last_discord_sync_at,
        discord_sync_status=view.discord_sync_status,
        last_discord_sync_error=view.last_discord_sync_error,
    )


def to_trade_sync_response(result: TradeSyncResult) -> TradeSyncResponse:
    """Format a service sync result into the public API response."""
    return TradeSyncResponse(
        league_id=result.league_id,
        status=result.status,
        trades_synced=result.trades_synced,
        commit_sha=result.commit_sha,
        synced_at=result.synced_at,
    )


def to_discord_sync_response(result: DiscordSyncTriggerResult) -> TradeDiscordSyncResponse:
    """Format a Discord sync trigger outcome into the public API response."""
    return TradeDiscordSyncResponse(
        league_id=result.league_id,
        status=result.status,
        message=result.message,
    )


def to_team_budget_projection_item(p: TeamBudgetProjection) -> TeamBudgetProjectionItem:
    """Format a domain budget projection into exact string values."""
    return TeamBudgetProjectionItem(
        team_id=p.team_id,
        starting_budget=p.starting_budget_str,
        base_trade_delta=p.base_trade_delta_str,
        fulfilled_conditional_delta=p.fulfilled_conditional_delta_str,
        net_delta=p.net_delta_str,
        projected_budget=p.projected_budget_str,
        pending_conditional_delta=p.pending_conditional_delta_str,
        is_negative_budget=p.is_negative_budget,
    )


def to_trades_list_response(league_id: int, trades: list[TradeView]) -> TradesListResponse:
    """Format service trade views into the public API response."""
    items: list[TradeItem] = []
    for t in trades:
        parties = [
            TradePartyItem(
                id=p.id,
                owner_id=p.owner_id,
                franchise_key=p.franchise_key,
                team_name_raw=p.team_name_raw,
                players_sent=p.players_sent,
                players_received=p.players_received,
                draft_picks_sent=p.draft_picks_sent,
                draft_picks_received=p.draft_picks_received,
                auction_dollars=[
                    BudgetDeltaItem(draft_year=d.draft_year, amount=f"{d.amount:.2f}")
                    for d in p.auction_dollars
                ],
            )
            for p in t.parties
        ]
        items.append(
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
    return TradesListResponse(league_id=league_id, trades=items)


def to_auction_budgets_response(view: AuctionBudgetsView) -> AuctionBudgetsResponse:
    """Format service auction budgets view into the public API response."""
    return AuctionBudgetsResponse(
        league_id=view.league_id,
        draft_year=view.draft_year,
        base_auction_budget=f"{view.base_auction_budget:.2f}",
        projections=[to_team_budget_projection_item(p) for p in view.projections],
    )
