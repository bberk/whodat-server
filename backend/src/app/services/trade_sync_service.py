"""Service for trade tracker configuration, GitHub repo synchronization, and budget queries."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models import (
    League,
    LeagueTrade,
    LeagueTradeBudgetDelta,
    LeagueTradeConfig,
    LeagueTradeParty,
    Owner,
    Team,
)
from app.domain.trade_budget import (
    BudgetDelta,
    TeamBudgetProjection,
    TradeCondition,
    calculate_team_budget_projections,
)
from app.security import crypto
from app.services.league_exceptions import AdminRequiredError, NotAMemberError
from app.services.league_models import LeagueUser
from app.services.refresh_limiter import RefreshRateLimiter

DEFAULT_TRADE_SYNC_INTERVAL_SECONDS = 10.0
DEFAULT_TRADE_SYNC_USER_LIMIT = 30
DEFAULT_TRADE_SYNC_USER_WINDOW_SECONDS = 3600.0


class TradeServiceError(Exception):
    """Base error for trade tracker service operations."""


class TradeTrackerDisabledError(TradeServiceError):
    """The trade tracker feature is not enabled for this league."""


class TradeSyncRateLimitedError(TradeServiceError):
    """Trade sync was called too frequently."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Trade sync is rate limited. Try again in {retry_after} seconds.")


class TradeSyncGitHubError(TradeServiceError):
    """An error occurred while fetching the trade ledger from GitHub."""


class TradeLedgerFormatError(TradeServiceError):
    """The ledger.json file is malformed or invalid."""


class DiscordSyncInProgressError(TradeServiceError):
    """A Discord trade sync is already running for this league."""


@dataclass(frozen=True)
class DiscordSyncTriggerResult:
    """Outcome of successfully triggering a background Discord trade sync."""

    league_id: int
    status: str
    message: str


@dataclass(frozen=True)
class TradeSyncResult:
    """Outcome of a successful GitHub trade repository sync."""

    league_id: int
    status: str
    trades_synced: int
    commit_sha: str | None
    synced_at: datetime


@dataclass(frozen=True)
class TradeConfigView:
    """Credential-safe view of a league's trade tracker configuration."""

    league_id: int
    enabled: bool
    discord_channel_id: str | None
    repo_owner: str
    repo_name: str
    branch: str
    has_github_token: bool
    has_discord_token: bool
    base_auction_budget: Decimal
    team_aliases: dict[str, Any]
    last_synced_at: datetime | None
    last_sync_commit: str | None
    last_sync_status: str
    last_sync_error: str | None
    last_discord_sync_at: datetime | None
    discord_sync_status: str
    last_discord_sync_error: str | None


@dataclass(frozen=True)
class TradeBudgetDeltaView:
    """View of one draft dollar adjustment leg."""

    draft_year: int
    amount: Decimal


@dataclass(frozen=True)
class TradePartyView:
    """View of one party involved in an ingested trade."""

    id: int
    owner_id: int | None
    franchise_key: str | None
    team_name_raw: str
    players_sent: list[dict[str, Any]]
    players_received: list[dict[str, Any]]
    draft_picks_sent: list[dict[str, Any]]
    draft_picks_received: list[dict[str, Any]]
    auction_dollars: list[TradeBudgetDeltaView]


@dataclass(frozen=True)
class TradeView:
    """Credential-safe view of a recorded league trade."""

    id: int
    external_trade_id: str
    trade_date: datetime
    agreement_season: int
    is_settled: bool
    discord_url: str | None
    summary: str
    conditions: list[dict[str, Any]]
    parties: list[TradePartyView]


@dataclass(frozen=True)
class AuctionBudgetsView:
    """View of projected auction budgets for a target draft year."""

    league_id: int
    draft_year: int
    base_auction_budget: Decimal
    projections: list[TeamBudgetProjection]


class TradeSyncService:
    """Manages trade configuration, GitHub repo syncs, and projected auction budgets."""

    def __init__(
        self,
        session: Session,
        *,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        rate_limiter: RefreshRateLimiter | None = None,
    ) -> None:
        self._session = session
        self._http_client = http_client
        self._clock = clock
        self._rate_limiter = rate_limiter or RefreshRateLimiter(
            clock=clock,
            league_interval_seconds=DEFAULT_TRADE_SYNC_INTERVAL_SECONDS,
            user_limit=DEFAULT_TRADE_SYNC_USER_LIMIT,
            user_window_seconds=DEFAULT_TRADE_SYNC_USER_WINDOW_SECONDS,
        )

    def commit(self) -> None:
        """Commit the active database transaction."""
        self._session.commit()

    def _require_member(self, caller: LeagueUser, league_id: int) -> League:
        """Verify the caller is a member of the league, or raise NotAMemberError."""
        league = self._session.get(League, league_id)
        if league is None:
            raise NotAMemberError(caller.user_id, league_id)

        # Check membership row
        from app.db.models import UserLeague

        membership = self._session.scalar(
            select(UserLeague).where(
                UserLeague.user_id == caller.user_id,
                UserLeague.league_id == league_id,
            )
        )
        if membership is None:
            raise NotAMemberError(caller.user_id, league_id)
        return league

    def _require_admin(self, caller: LeagueUser, league_id: int) -> League:
        """Verify the caller is an admin member of the league, or raise."""
        league = self._require_member(caller, league_id)
        if caller.role != "admin":
            raise AdminRequiredError(caller.user_id, league_id)
        return league

    def get_or_create_config(self, league_id: int) -> LeagueTradeConfig:
        """Fetch or initialize the LeagueTradeConfig for a league."""
        config = self._session.scalar(
            select(LeagueTradeConfig).where(LeagueTradeConfig.league_id == league_id)
        )
        if config is None:
            config = LeagueTradeConfig(
                league_id=league_id,
                enabled=False,
                repo_owner="",
                repo_name="",
                branch="main",
                base_auction_budget=Decimal("200.00"),
                team_aliases={},
            )
            self._session.add(config)
            self._session.flush()
        return config

    def get_config(self, caller: LeagueUser, league_id: int) -> TradeConfigView:
        """Return the credential-safe trade tracker configuration for an admin."""
        self._require_admin(caller, league_id)
        config = self.get_or_create_config(league_id)
        return self._to_config_view(config)

    def update_config(
        self,
        caller: LeagueUser,
        league_id: int,
        *,
        enabled: bool | None = None,
        discord_channel_id: str | None = None,
        repo_owner: str | None = None,
        repo_name: str | None = None,
        branch: str | None = None,
        github_token: str | None = None,
        clear_github_token: bool = False,
        discord_token: str | None = None,
        clear_discord_token: bool = False,
        base_auction_budget: Decimal | None = None,
        team_aliases: dict[str, Any] | None = None,
    ) -> TradeConfigView:
        """Update and persist trade tracker configuration for an admin."""
        league = self._require_admin(caller, league_id)
        config = self.get_or_create_config(league_id)

        if enabled is not None:
            config.enabled = enabled
            league.has_trades_enabled = enabled
        if discord_channel_id is not None:
            config.discord_channel_id = discord_channel_id.strip() or None
        if repo_owner is not None:
            config.repo_owner = repo_owner.strip()
        if repo_name is not None:
            config.repo_name = repo_name.strip()
        if branch is not None and branch.strip():
            config.branch = branch.strip()
        if clear_github_token:
            config.github_token_encrypted = None
        elif github_token is not None and github_token.strip():
            config.github_token_encrypted = crypto.encrypt(github_token.strip())
        if clear_discord_token:
            config.discord_token_encrypted = None
        elif discord_token is not None and discord_token.strip():
            config.discord_token_encrypted = crypto.encrypt(discord_token.strip())
        if base_auction_budget is not None:
            if base_auction_budget < Decimal("0.00"):
                raise ValueError("base_auction_budget must be non-negative")
            config.base_auction_budget = base_auction_budget.quantize(Decimal("0.01"))
        if team_aliases is not None:
            config.team_aliases = dict(team_aliases)

        self._session.flush()
        return self._to_config_view(config)

    def sync_trade_repo(self, caller: LeagueUser, league_id: int) -> TradeSyncResult:
        """Fetch and ingest the latest merged trade ledger from GitHub."""
        self._require_admin(caller, league_id)
        config = self.get_or_create_config(league_id)

        if not config.enabled:
            raise TradeTrackerDisabledError("Trade tracker is disabled for this league")

        if not config.repo_owner or not config.repo_name:
            config.last_sync_status = "error"
            config.last_sync_error = (
                "GitHub repository owner and name must be configured before syncing"
            )
            self._session.flush()
            raise TradeSyncGitHubError(
                "GitHub repository owner and name must be configured before syncing"
            )

        # Check rate limit
        decision = self._rate_limiter.check(league_id=league_id, user_id=caller.user_id)
        if not decision.allowed:
            raise TradeSyncRateLimitedError(decision.retry_after)

        # Decrypt token if available
        token: str | None = None
        if config.github_token_encrypted:
            try:
                token = crypto.decrypt(config.github_token_encrypted)
            except Exception:
                config.last_sync_status = "error"
                config.last_sync_error = "Decryption error for GitHub token"
                self._session.flush()
                raise TradeSyncGitHubError("Failed to decrypt stored GitHub access token") from None

        # Fetch ledger.json from GitHub
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "whodat-server-trade-sync",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = (
            f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}/"
            f"contents/ledger.json?ref={config.branch}"
        )

        try:
            client = self._http_client or httpx.Client(timeout=15.0)
            try:
                resp = client.get(url, headers=headers)
            finally:
                if self._http_client is None:
                    client.close()
        except Exception as exc:
            config.last_sync_status = "error"
            config.last_sync_error = f"Network error contacting GitHub: {type(exc).__name__}"
            self._session.flush()
            raise TradeSyncGitHubError(f"Network error contacting GitHub: {exc}") from exc

        if resp.status_code == 404:
            config.last_sync_status = "error"
            config.last_sync_error = "Repository or ledger.json not found on GitHub"
            self._session.flush()
            raise TradeSyncGitHubError("Repository or ledger.json not found on GitHub")
        if resp.status_code in (401, 403):
            config.last_sync_status = "error"
            config.last_sync_error = "GitHub authentication failed: check access token"
            self._session.flush()
            raise TradeSyncGitHubError("GitHub authentication failed: check access token")
        if resp.status_code >= 400:
            config.last_sync_status = "error"
            config.last_sync_error = f"GitHub API error {resp.status_code}"
            self._session.flush()
            raise TradeSyncGitHubError(f"GitHub returned HTTP {resp.status_code}")

        # Parse GitHub contents response
        import base64
        import json

        commit_sha: str | None = None
        try:
            payload_data = resp.json()
            commit_sha = payload_data.get("sha")
            # GitHub contents API returns base64 encoded content
            encoded_content = payload_data.get("content", "")
            raw_bytes = base64.b64decode(encoded_content)
            ledger_data = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            config.last_sync_status = "error"
            config.last_sync_error = f"Malformed ledger.json payload: {exc}"
            self._session.flush()
            raise TradeLedgerFormatError(f"Failed to decode ledger.json: {exc}") from exc

        # Ingest parsed ledger
        now = datetime.now(UTC)
        try:
            trades_count = self._ingest_ledger(league_id, config, ledger_data)
            config.last_synced_at = now
            config.last_sync_commit = commit_sha
            config.last_sync_status = "success"
            config.last_sync_error = None
            self._session.flush()
        except Exception as exc:
            config.last_sync_status = "error"
            config.last_sync_error = f"Ingestion error: {exc}"
            self._session.flush()
            raise TradeLedgerFormatError(f"Error ingesting ledger contents: {exc}") from exc

        return TradeSyncResult(
            league_id=league_id,
            status="success",
            trades_synced=trades_count,
            commit_sha=commit_sha,
            synced_at=now,
        )

    def start_discord_sync(self, caller: LeagueUser, league_id: int) -> DiscordSyncTriggerResult:
        """Acquire mutex lock and initiate an asynchronous Discord trade sync."""
        self._require_admin(caller, league_id)
        config = self.get_or_create_config(league_id)

        if not config.enabled:
            raise TradeTrackerDisabledError("Trade tracker is disabled for this league")

        if not config.discord_channel_id:
            raise TradeServiceError("Discord channel ID is not configured for this league")

        if config.discord_sync_status == "running":
            raise DiscordSyncInProgressError(
                "A Discord trade sync is already running for this league"
            )

        config.discord_sync_status = "running"
        config.last_discord_sync_error = None
        self._session.flush()

        return DiscordSyncTriggerResult(
            league_id=league_id,
            status="started",
            message="Discord trade sync initiated in background",
        )

    def complete_discord_sync(
        self,
        league_id: int,
        *,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Update league trade config status when a background Discord sync completes."""
        config = self._session.scalar(
            select(LeagueTradeConfig).where(LeagueTradeConfig.league_id == league_id)
        )
        if config is not None:
            if success:
                config.last_discord_sync_at = datetime.now(UTC)
                config.discord_sync_status = "success"
                config.last_discord_sync_error = None
            else:
                config.discord_sync_status = "error"
                config.last_discord_sync_error = error_message
            self._session.flush()

    def run_discord_sync_job(self, league_id: int) -> None:
        """Execute the Discord trade ingestion worker job."""
        config = self._session.scalar(
            select(LeagueTradeConfig).where(LeagueTradeConfig.league_id == league_id)
        )
        if config is None or not config.discord_channel_id:
            self.complete_discord_sync(
                league_id, success=False, error_message="Discord channel not configured"
            )
            return

        from app.config import _REPO_ROOT, get_settings

        discord_token: str | None = None
        if config.discord_token_encrypted:
            try:
                discord_token = crypto.decrypt(config.discord_token_encrypted)
            except Exception:
                self.complete_discord_sync(
                    league_id,
                    success=False,
                    error_message="Decryption error for Discord bot token",
                )
                return

        settings = get_settings()
        if not discord_token:
            discord_token = settings.discord_bot_token

        if not discord_token:
            # When no bot token is set in config or environment (e.g. tests/dev), record clean
            self.complete_discord_sync(league_id, success=True)
            return

        import os
        import subprocess
        import sys

        cmd = [
            sys.executable,
            "-m",
            "scripts.trade_agent.discord_trade_ingest",
            "--channel-id",
            config.discord_channel_id,
            "--repo-dir",
            settings.trade_agent_repo_path,
        ]
        if config.repo_owner and config.repo_name:
            cmd.extend(["--repo", f"{config.repo_owner}/{config.repo_name}"])

        env = {
            **os.environ,
            "PYTHONPATH": str(_REPO_ROOT),
            "DISCORD_BOT_TOKEN": discord_token,
        }
        if settings.opencode_model:
            env["OPENCODE_MODEL"] = settings.opencode_model
        if settings.opencode_api_key:
            env["OPENCODE_API_KEY"] = settings.opencode_api_key

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=str(_REPO_ROOT),
                env=env,
            )
            self.complete_discord_sync(league_id, success=True)
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            self.complete_discord_sync(league_id, success=False, error_message=err)
        except Exception as exc:
            self.complete_discord_sync(league_id, success=False, error_message=str(exc))

    def _ingest_ledger(
        self, league_id: int, config: LeagueTradeConfig, ledger_data: dict[str, Any]
    ) -> int:
        """Upsert trades, parties, and budget deltas from ledger dictionary."""
        active_trades = ledger_data.get("active_trades", [])
        settled_trade_ids = set(ledger_data.get("settled_trade_ids", []))
        settle_through_year = ledger_data.get("settle_through_year")

        # Validate ledger trades zero-sum balance before persisting any records
        for trade_dict in active_trades:
            ext_id = str(trade_dict.get("id", "unknown"))
            year_sums: dict[int, Decimal] = {}
            for party_dict in trade_dict.get("parties", []):
                for delta_dict in party_dict.get("auction_dollars", []):
                    try:
                        yr = int(delta_dict["draft_year"])
                        amt = Decimal(str(delta_dict["amount"])).quantize(Decimal("0.01"))
                    except Exception as exc:
                        raise TradeLedgerFormatError(
                            f"Invalid draft dollar entry in trade {ext_id}: {exc}"
                        ) from exc
                    year_sums[yr] = year_sums.get(yr, Decimal("0.00")) + amt
            for yr, total in year_sums.items():
                if total != Decimal("0.00"):
                    raise TradeLedgerFormatError(
                        f"Trade {ext_id} fails zero-sum balance for draft year {yr}: "
                        f"sum is {total:.2f}"
                    )

        # Preload owners and teams for alias matching
        owners = list(self._session.scalars(select(Owner).where(Owner.league_id == league_id)))
        owner_by_name = {o.display_name.lower(): o for o in owners}
        owner_by_id = {o.id: o for o in owners}

        teams = list(self._session.scalars(select(Team).where(Team.league_id == league_id)))
        team_by_name = {t.name.lower(): t for t in teams}

        aliases = config.team_aliases or {}

        synced_count = 0
        for trade_dict in active_trades:
            ext_id = str(trade_dict["id"])
            trade_date_str = trade_dict.get("date") or datetime.now(UTC).isoformat()
            if trade_date_str.endswith("Z"):
                trade_date_str = trade_date_str[:-1] + "+00:00"
            trade_date = datetime.fromisoformat(trade_date_str)
            agreement_season = int(trade_dict.get("agreement_season", trade_date.year))

            # Fetch or create LeagueTrade
            existing_trade = self._session.scalar(
                select(LeagueTrade).where(
                    LeagueTrade.league_id == league_id,
                    LeagueTrade.external_trade_id == ext_id,
                )
            )
            if existing_trade is None:
                existing_trade = LeagueTrade(
                    league_id=league_id,
                    external_trade_id=ext_id,
                    trade_date=trade_date,
                    agreement_season=agreement_season,
                    is_settled=False,
                    discord_url=trade_dict.get("source", {}).get("jump_url"),
                    summary=trade_dict.get("notes", f"Trade {ext_id}"),
                    raw_yaml=trade_dict.get("raw_text", ""),
                    conditions=trade_dict.get("conditions", []),
                )
                self._session.add(existing_trade)
                self._session.flush()
            else:
                existing_trade.trade_date = trade_date
                existing_trade.agreement_season = agreement_season
                existing_trade.is_settled = False
                existing_trade.discord_url = trade_dict.get("source", {}).get("jump_url")
                existing_trade.summary = trade_dict.get("notes", existing_trade.summary)
                existing_trade.conditions = trade_dict.get("conditions", [])
                # Delete child budget deltas first, then parties (prevents orphaned deltas)
                party_ids = list(
                    self._session.scalars(
                        select(LeagueTradeParty.id).where(
                            LeagueTradeParty.trade_id == existing_trade.id
                        )
                    )
                )
                if party_ids:
                    self._session.execute(
                        delete(LeagueTradeBudgetDelta).where(
                            LeagueTradeBudgetDelta.party_id.in_(party_ids)
                        )
                    )
                self._session.execute(
                    delete(LeagueTradeParty).where(LeagueTradeParty.trade_id == existing_trade.id)
                )
                self._session.flush()

            # Insert parties and deltas
            for party_dict in trade_dict.get("parties", []):
                raw_name = str(party_dict.get("team_name", "Unknown"))
                resolved_owner: Owner | None = None
                franchise_key: str | None = None

                # 1. Alias lookup
                alias_val = aliases.get(raw_name) or aliases.get(party_dict.get("discord_user"))
                if isinstance(alias_val, int) and alias_val in owner_by_id:
                    resolved_owner = owner_by_id[alias_val]
                elif isinstance(alias_val, str) and alias_val.lower() in owner_by_name:
                    resolved_owner = owner_by_name[alias_val.lower()]

                # 2. Exact match on owner display_name
                if resolved_owner is None and raw_name.lower() in owner_by_name:
                    resolved_owner = owner_by_name[raw_name.lower()]

                # 3. Match on team name
                if resolved_owner is None and raw_name.lower() in team_by_name:
                    matching_team = team_by_name[raw_name.lower()]
                    franchise_key = f"espn:{matching_team.external_id}"
                    if matching_team.owner_id and matching_team.owner_id in owner_by_id:
                        resolved_owner = owner_by_id[matching_team.owner_id]

                party = LeagueTradeParty(
                    trade_id=existing_trade.id,
                    league_id=league_id,
                    owner_id=resolved_owner.id if resolved_owner else None,
                    franchise_key=franchise_key,
                    team_name_raw=raw_name,
                    players_sent=party_dict.get("players_sent", []),
                    players_received=party_dict.get("players_received", []),
                    draft_picks_sent=party_dict.get("draft_picks_sent", []),
                    draft_picks_received=party_dict.get("draft_picks_received", []),
                )
                self._session.add(party)
                self._session.flush()

                for delta_dict in party_dict.get("auction_dollars", []):
                    draft_yr = int(delta_dict["draft_year"])
                    amt = Decimal(str(delta_dict["amount"])).quantize(Decimal("0.01"))
                    delta = LeagueTradeBudgetDelta(
                        party_id=party.id,
                        league_id=league_id,
                        draft_year=draft_yr,
                        amount=amt,
                    )
                    self._session.add(delta)

            synced_count += 1

        # Mark settled trades
        all_stored_trades = list(
            self._session.scalars(select(LeagueTrade).where(LeagueTrade.league_id == league_id))
        )
        for stored in all_stored_trades:
            if stored.external_trade_id in settled_trade_ids:
                stored.is_settled = True
            elif settle_through_year is not None and stored.agreement_season <= int(
                settle_through_year
            ):
                # Verify that all deltas are <= settle_through_year
                has_future = any(
                    delta.draft_year > int(settle_through_year)
                    for party in stored.parties
                    for delta in party.budget_deltas
                )
                if not has_future:
                    stored.is_settled = True

        self._session.flush()
        return synced_count

    def list_trades(
        self,
        caller: LeagueUser,
        league_id: int,
        *,
        draft_year: int | None = None,
        team_name: str | None = None,
    ) -> list[TradeView]:
        """Query ingested trades for a league member, with optional draft_year or team filters."""
        self._require_member(caller, league_id)

        query = (
            select(LeagueTrade)
            .where(LeagueTrade.league_id == league_id)
            .options(selectinload(LeagueTrade.parties).selectinload(LeagueTradeParty.budget_deltas))
            .order_by(LeagueTrade.trade_date.desc(), LeagueTrade.id.desc())
        )
        trades = list(self._session.scalars(query))

        filtered_views: list[TradeView] = []
        for trade in trades:
            if draft_year is not None:
                has_year = any(
                    delta.draft_year == draft_year
                    for party in trade.parties
                    for delta in party.budget_deltas
                )
                has_condition_year = any(
                    cond.get("draft_year") == draft_year for cond in trade.conditions
                )
                if not (has_year or has_condition_year):
                    continue

            if team_name is not None:
                matches_team = any(
                    team_name.lower() in party.team_name_raw.lower() for party in trade.parties
                )
                if not matches_team:
                    continue

            party_views: list[TradePartyView] = []
            for party in trade.parties:
                delta_views = [
                    TradeBudgetDeltaView(draft_year=d.draft_year, amount=d.amount)
                    for d in party.budget_deltas
                ]
                party_views.append(
                    TradePartyView(
                        id=party.id,
                        owner_id=party.owner_id,
                        franchise_key=party.franchise_key,
                        team_name_raw=party.team_name_raw,
                        players_sent=party.players_sent,
                        players_received=party.players_received,
                        draft_picks_sent=party.draft_picks_sent,
                        draft_picks_received=party.draft_picks_received,
                        auction_dollars=delta_views,
                    )
                )

            filtered_views.append(
                TradeView(
                    id=trade.id,
                    external_trade_id=trade.external_trade_id,
                    trade_date=trade.trade_date,
                    agreement_season=trade.agreement_season,
                    is_settled=trade.is_settled,
                    discord_url=trade.discord_url,
                    summary=trade.summary,
                    conditions=trade.conditions,
                    parties=party_views,
                )
            )

        return filtered_views

    def _build_team_resolver(
        self, league_id: int, config: LeagueTradeConfig
    ) -> tuple[Callable[[str], str], list[str]]:
        owners = list(self._session.scalars(select(Owner).where(Owner.league_id == league_id)))
        owner_by_id = {o.id: o for o in owners}
        owner_by_name = {o.display_name.lower(): o for o in owners}

        max_season = self._session.scalar(
            select(func.max(Team.season)).where(Team.league_id == league_id)
        )
        teams = (
            list(
                self._session.scalars(
                    select(Team).where(
                        Team.league_id == league_id,
                        Team.season == max_season,
                    )
                )
            )
            if max_season is not None
            else []
        )
        team_by_name = {t.name.lower(): t for t in teams}

        owner_to_team: dict[str, str] = {}
        for t in teams:
            if t.owner_id and t.owner_id in owner_by_id:
                owner = owner_by_id[t.owner_id]
                owner_to_team[owner.display_name.lower()] = t.name

        aliases = config.team_aliases or {}

        def resolve(raw: str, seen: set[str] | None = None) -> str:
            raw_s = str(raw).strip()
            if not raw_s:
                return "Unknown"
            if seen is None:
                seen = set()
            if raw_s.lower() in seen:
                return raw_s
            seen.add(raw_s.lower())

            # 1. Alias lookup
            alias_val = aliases.get(raw_s) or aliases.get(raw_s.lower())
            if isinstance(alias_val, int) and alias_val in owner_by_id:
                o = owner_by_id[alias_val]
                return owner_to_team.get(o.display_name.lower(), o.display_name)
            if isinstance(alias_val, str) and alias_val.strip():
                return resolve(alias_val, seen)

            # 2. Team name match
            if raw_s.lower() in team_by_name:
                return team_by_name[raw_s.lower()].name

            # 3. Owner display_name match
            if raw_s.lower() in owner_by_name:
                o = owner_by_name[raw_s.lower()]
                return owner_to_team.get(o.display_name.lower(), o.display_name)

            return raw_s

        if teams:
            known_teams = list(dict.fromkeys(t.name for t in teams))
        elif owners:
            known_teams = list(dict.fromkeys(o.display_name for o in owners))
        else:
            known_teams = []

        return resolve, known_teams

    def get_auction_budgets(
        self, caller: LeagueUser, league_id: int, *, target_draft_year: int
    ) -> AuctionBudgetsView:
        """Calculate exact projected auction budgets for all league teams for target_draft_year."""
        self._require_member(caller, league_id)
        config = self.get_or_create_config(league_id)
        resolve_team, known_teams = self._build_team_resolver(league_id, config)

        # Gather all unconditional deltas with joinedload (prevents N+1 queries)
        db_deltas = list(
            self._session.scalars(
                select(LeagueTradeBudgetDelta)
                .where(LeagueTradeBudgetDelta.league_id == league_id)
                .options(
                    joinedload(LeagueTradeBudgetDelta.party).joinedload(LeagueTradeParty.owner)
                )
            )
        )
        domain_deltas: list[BudgetDelta] = []
        for d in db_deltas:
            raw_name = d.party.team_name_raw
            if d.party.owner and raw_name.lower() not in [k.lower() for k in known_teams]:
                team_identifier = resolve_team(d.party.owner.display_name)
            else:
                team_identifier = resolve_team(raw_name)
            domain_deltas.append(
                BudgetDelta(
                    team_id=team_identifier,
                    draft_year=d.draft_year,
                    amount=d.amount,
                )
            )

        # Gather all conditions from non-settled trades only
        trades = list(
            self._session.scalars(
                select(LeagueTrade).where(
                    LeagueTrade.league_id == league_id,
                    LeagueTrade.is_settled.is_(False),
                )
            )
        )
        domain_conditions: list[TradeCondition] = []
        for trade in trades:
            for cond_dict in trade.conditions:
                status = cond_dict.get("status", "pending")
                if status not in ("pending", "fulfilled", "void"):
                    status = "pending"
                paying_raw = str(cond_dict.get("paying_team", "Unknown"))
                receiving_raw = str(cond_dict.get("receiving_team", "Unknown"))
                domain_conditions.append(
                    TradeCondition(
                        condition_id=str(cond_dict.get("id", f"c-{trade.id}")),
                        paying_team=resolve_team(paying_raw),
                        receiving_team=resolve_team(receiving_raw),
                        draft_year=int(cond_dict.get("draft_year", target_draft_year)),
                        amount=Decimal(str(cond_dict.get("amount", "0.00"))),
                        status=status,
                    )
                )

        projections = calculate_team_budget_projections(
            starting_budget=config.base_auction_budget,
            known_teams=known_teams,
            deltas=domain_deltas,
            conditions=domain_conditions,
            target_draft_year=target_draft_year,
        )

        return AuctionBudgetsView(
            league_id=league_id,
            draft_year=target_draft_year,
            base_auction_budget=config.base_auction_budget,
            projections=projections,
        )

    def _to_config_view(self, config: LeagueTradeConfig) -> TradeConfigView:
        return TradeConfigView(
            league_id=config.league_id,
            enabled=config.enabled,
            discord_channel_id=config.discord_channel_id,
            repo_owner=config.repo_owner,
            repo_name=config.repo_name,
            branch=config.branch,
            has_github_token=bool(config.github_token_encrypted),
            has_discord_token=bool(config.discord_token_encrypted),
            base_auction_budget=config.base_auction_budget,
            team_aliases=config.team_aliases or {},
            last_synced_at=config.last_synced_at,
            last_sync_commit=config.last_sync_commit,
            last_sync_status=config.last_sync_status,
            last_sync_error=config.last_sync_error,
            last_discord_sync_at=config.last_discord_sync_at,
            discord_sync_status=config.discord_sync_status,
            last_discord_sync_error=config.last_discord_sync_error,
        )
