"""HTTP acceptance tests for Trade Tracker settings, sync operations, and auction budget API."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.main import create_app
from app.api.routes_trades import get_trade_sync_service
from app.api.session import SESSION_COOKIE_NAME, set_session
from app.config import get_settings
from app.db.auth_repositories import MembershipRepository, UserRepository
from app.db.base import Base
from app.db.models import League, LeagueTradeConfig, Owner, Team
from app.db.session import get_session as db_get_session
from app.services.refresh_limiter import RefreshRateLimiter
from app.services.trade_sync_service import TradeSyncService


@pytest.fixture(autouse=True)
def _configure_credential_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    get_settings.cache_clear()
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(bytes(range(32))).decode("ascii"))
    yield
    get_settings.cache_clear()


@dataclass
class Api:
    """A test application, test client, and database session factory."""

    client: TestClient
    factory: sessionmaker[Session]
    mock_transport: httpx.MockTransport | None = None


@pytest.fixture
def api_factory(tmp_path: Path) -> Iterator[Callable[..., Api]]:
    engines: list[Engine] = []

    def build(*, mock_handler: Callable[[httpx.Request], httpx.Response] | None = None) -> Api:
        engine = create_engine(f"sqlite:///{tmp_path / f'trades-{len(engines)}.db'}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        app = create_app()

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        transport = httpx.MockTransport(mock_handler) if mock_handler else None
        shared_limiter = RefreshRateLimiter(
            league_interval_seconds=10.0,
            user_limit=30,
            user_window_seconds=3600.0,
        )

        def override_trade_service() -> Iterator[TradeSyncService]:
            with factory() as session:
                http_client = httpx.Client(transport=transport) if transport else None
                yield TradeSyncService(
                    session, http_client=http_client, rate_limiter=shared_limiter
                )

        app.dependency_overrides[db_get_session] = override_session
        app.dependency_overrides[get_trade_sync_service] = override_trade_service
        return Api(client=TestClient(app), factory=factory, mock_transport=transport)

    try:
        yield build
    finally:
        for engine in engines:
            Base.metadata.drop_all(engine)
            engine.dispose()


def seed_league(api: Api, *, name: str = "Trade League", has_trades: bool = True) -> int:
    with api.factory() as session:
        league = League(
            provider="espn",
            external_id=f"ext-{name.lower().replace(' ', '-')}",
            name=name,
            league_metadata={},
            provider_config_ref="fake",
            has_trades_enabled=has_trades,
        )
        session.add(league)
        session.flush()

        # Seed owners
        owner_a = Owner(league_id=league.id, external_id="o1", display_name="Alice")
        owner_b = Owner(league_id=league.id, external_id="o2", display_name="Bob")
        session.add_all([owner_a, owner_b])
        session.flush()

        # Seed teams
        team_a = Team(
            league_id=league.id,
            season=2026,
            external_id="1",
            name="Team Alice",
            owner_id=owner_a.id,
        )
        team_b = Team(
            league_id=league.id,
            season=2026,
            external_id="2",
            name="Team Bob",
            owner_id=owner_b.id,
        )
        session.add_all([team_a, team_b])
        session.commit()
        return league.id


def create_user(api: Api, email: str, *, league_id: int | None, role: str = "member") -> int:
    with api.factory() as session:
        user = UserRepository(session).create(email, "unused-hash")
        user.role = role
        if league_id is not None:
            MembershipRepository(session).create(user.id, league_id)
        session.commit()
        return user.id


def login(api: Api, user_id: int) -> None:
    response = Response()
    set_session(response, user_id)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)


def test_trade_config_authorization_boundaries(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)

    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    member_id = create_user(api, "member@example.com", league_id=league_id, role="member")
    outsider_id = create_user(api, "outsider@example.com", league_id=None, role="admin")

    path = f"/api/v1/leagues/{league_id}/trade-config"

    # Anonymous -> 401
    assert api.client.get(path).status_code == 401

    # Outsider -> 404 (league not disclosed)
    login(api, outsider_id)
    assert api.client.get(path).status_code == 404

    # Member -> 403 Forbidden
    login(api, member_id)
    assert api.client.get(path).status_code == 403

    # Admin -> 200 OK
    login(api, admin_id)
    resp = api.client.get(path)
    assert resp.status_code == 200
    data = resp.json()
    assert data["league_id"] == league_id
    assert data["enabled"] is False
    assert data["repo_owner"] == ""
    assert data["repo_name"] == ""
    assert data["has_github_token"] is False
    assert data["has_discord_token"] is False
    assert data["base_auction_budget"] == "200.00"


def test_update_trade_config_and_token_encryption(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    path = f"/api/v1/leagues/{league_id}/trade-config"

    # Update config and set GitHub & Discord tokens
    update_payload = {
        "enabled": True,
        "discord_channel_id": "999888777",
        "repo_owner": "custom-owner",
        "repo_name": "custom-trades",
        "branch": "develop",
        "github_token": "ghp_secrettoken12345",
        "discord_token": "bot-secret-token-xyz",
        "base_auction_budget": "250.00",
        "team_aliases": {"alice_tag": "Alice"},
    }
    resp = api.client.put(path, json=update_payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["enabled"] is True
    assert data["discord_channel_id"] == "999888777"
    assert data["repo_owner"] == "custom-owner"
    assert data["repo_name"] == "custom-trades"
    assert data["branch"] == "develop"
    assert data["has_github_token"] is True
    assert data["has_discord_token"] is True
    assert data["base_auction_budget"] == "250.00"
    assert data["team_aliases"] == {"alice_tag": "Alice"}

    # Tokens are never returned in response body
    assert "ghp_secrettoken12345" not in resp.text
    assert "bot-secret-token-xyz" not in resp.text

    # Verify encrypted in DB
    with api.factory() as session:
        cfg = session.query(LeagueTradeConfig).filter_by(league_id=league_id).one()
        assert cfg.github_token_encrypted is not None
        assert "ghp_secrettoken12345" not in cfg.github_token_encrypted
        assert cfg.discord_token_encrypted is not None
        assert "bot-secret-token-xyz" not in cfg.discord_token_encrypted

    # Clear tokens
    resp_clear = api.client.put(
        path, json={"clear_github_token": True, "clear_discord_token": True}
    )
    assert resp_clear.status_code == 200
    clear_data = resp_clear.json()
    assert clear_data["has_github_token"] is False
    assert clear_data["has_discord_token"] is False


def test_sync_trade_repo_disabled_error(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # By default, enabled is False -> 400
    sync_path = f"/api/v1/leagues/{league_id}/trades/sync"
    resp = api.client.post(sync_path)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "trade_tracker_disabled"


def test_sync_trade_repo_success_and_budget_calculation(api_factory: Callable[..., Api]) -> None:
    # Build ledger payload
    ledger_content = {
        "version": 1,
        "last_compiled_at": "2026-11-07T18:00:00Z",
        "settle_through_year": 2026,
        "settled_trade_ids": ["trade-old"],
        "active_trades": [
            {
                "id": "trade-2027-1",
                "date": "2026-11-07T16:00:00Z",
                "agreement_season": 2026,
                "source": {
                    "jump_url": "https://discord.com/channels/1/2/3",
                },
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "discord_user": "alice_ff",
                        "players_sent": [{"name": "Patrick Mahomes"}],
                        "players_received": [{"name": "Justin Jefferson"}],
                        "draft_picks_sent": [{"draft_year": 2027, "round": 1}],
                        "draft_picks_received": [],
                        "auction_dollars": [
                            {"draft_year": 2027, "amount": -5.00},
                            {"draft_year": 2028, "amount": -10.00},
                        ],
                    },
                    {
                        "team_name": "Team Bob",
                        "discord_user": "bob_commish",
                        "players_sent": [{"name": "Justin Jefferson"}],
                        "players_received": [{"name": "Patrick Mahomes"}],
                        "draft_picks_sent": [],
                        "draft_picks_received": [{"draft_year": 2027, "round": 1}],
                        "auction_dollars": [
                            {"draft_year": 2027, "amount": 5.00},
                            {"draft_year": 2028, "amount": 10.00},
                        ],
                    },
                ],
                "conditions": [
                    {
                        "id": "c1",
                        "description": "If Mahomes MVP, Bob pays $5 in 2027",
                        "draft_year": 2027,
                        "paying_team": "Team Bob",
                        "receiving_team": "Team Alice",
                        "amount": 5.00,
                        "status": "fulfilled",
                    }
                ],
                "notes": "Mahomes + 2027 1st + $5 2027 + $10 2028 for Justin Jefferson",
            }
        ],
    }

    raw_json_bytes = json.dumps(ledger_content).encode("utf-8")
    github_response_body = json.dumps(
        {
            "sha": "7b3e1a9f",
            "content": base64.b64encode(raw_json_bytes).decode("ascii"),
            "encoding": "base64",
        }
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "contents/ledger.json" in str(request.url):
            return httpx.Response(200, text=github_response_body)
        return httpx.Response(404, text='{"message": "Not Found"}')

    api = api_factory(mock_handler=mock_handler)
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    member_id = create_user(api, "member@example.com", league_id=league_id, role="member")
    login(api, admin_id)

    # Enable trade tracker
    config_path = f"/api/v1/leagues/{league_id}/trade-config"
    api.client.put(
        config_path,
        json={
            "enabled": True,
            "base_auction_budget": "200.00",
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )

    # Trigger sync
    sync_path = f"/api/v1/leagues/{league_id}/trades/sync"
    sync_resp = api.client.post(sync_path)
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["status"] == "success"
    assert sync_data["trades_synced"] == 1
    assert sync_data["commit_sha"] == "7b3e1a9f"

    # Query trades list as regular member
    login(api, member_id)
    trades_path = f"/api/v1/leagues/{league_id}/trades"
    trades_resp = api.client.get(trades_path)
    assert trades_resp.status_code == 200
    trades_data = trades_resp.json()["trades"]
    assert len(trades_data) == 1
    t = trades_data[0]
    assert t["external_trade_id"] == "trade-2027-1"
    assert len(t["parties"]) == 2

    # Query auction budget for 2027
    budget_2027_path = f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027"
    budget_resp = api.client.get(budget_2027_path)
    assert budget_resp.status_code == 200
    b_data = budget_resp.json()
    assert b_data["draft_year"] == 2027
    assert b_data["base_auction_budget"] == "200.00"

    projections = {p["team_id"]: p for p in b_data["projections"]}
    # In 2027:
    # Alice: base -5, fulfilled condition +5 -> net 0.00 -> projected 200.00
    alice = projections["Team Alice"]
    assert alice["starting_budget"] == "200.00"
    assert alice["base_trade_delta"] == "-5.00"
    assert alice["fulfilled_conditional_delta"] == "5.00"
    assert alice["net_delta"] == "0.00"
    assert alice["projected_budget"] == "200.00"

    # Bob: base +5, fulfilled condition -5 -> net 0.00 -> projected 200.00
    bob = projections["Team Bob"]
    assert bob["base_trade_delta"] == "5.00"
    assert bob["fulfilled_conditional_delta"] == "-5.00"
    assert bob["projected_budget"] == "200.00"

    # Query auction budget for 2028
    budget_2028_path = f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2028"
    budget_2028_resp = api.client.get(budget_2028_path)
    assert budget_2028_resp.status_code == 200
    b_2028_data = budget_2028_resp.json()

    projections_2028 = {p["team_id"]: p for p in b_2028_data["projections"]}
    # In 2028:
    # Alice: -10 -> projected 190.00
    assert projections_2028["Team Alice"]["net_delta"] == "-10.00"
    assert projections_2028["Team Alice"]["projected_budget"] == "190.00"
    # Bob: +10 -> projected 210.00
    assert projections_2028["Team Bob"]["net_delta"] == "10.00"
    assert projections_2028["Team Bob"]["projected_budget"] == "210.00"


def test_sync_rate_limiting(api_factory: Callable[..., Api]) -> None:
    api = api_factory(mock_handler=lambda req: httpx.Response(404))
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    config_path = f"/api/v1/leagues/{league_id}/trade-config"
    api.client.put(
        config_path,
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )

    sync_path = f"/api/v1/leagues/{league_id}/trades/sync"
    # First sync fails with 502 (404 from GitHub mock)
    first_resp = api.client.post(sync_path)
    assert first_resp.status_code == 502

    # Second sync immediately after hits rate limiter -> 429
    second_resp = api.client.post(sync_path)
    assert second_resp.status_code == 429
    assert second_resp.json()["detail"]["code"] == "rate_limited"
    assert "Retry-After" in second_resp.headers


def test_trade_endpoints_authorization(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)

    member_id = create_user(api, "member@example.com", league_id=league_id, role="member")
    outsider_id = create_user(api, "outsider@example.com", league_id=None, role="member")

    # Member can view trades and budgets, but cannot sync
    login(api, member_id)
    assert api.client.get(f"/api/v1/leagues/{league_id}/trades").status_code == 200
    assert (
        api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027").status_code
        == 200
    )
    assert api.client.post(f"/api/v1/leagues/{league_id}/trades/sync").status_code == 403

    # Outsider cannot view anything -> 404
    login(api, outsider_id)
    assert api.client.get(f"/api/v1/leagues/{league_id}/trades").status_code == 404
    assert (
        api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027").status_code
        == 404
    )
    assert api.client.post(f"/api/v1/leagues/{league_id}/trades/sync").status_code == 404


def test_list_trades_filters_and_reingest(api_factory: Callable[..., Api]) -> None:
    ledger_content = {
        "version": 1,
        "active_trades": [
            {
                "id": "t-1",
                "date": "2026-10-01T12:00:00Z",
                "agreement_season": 2026,
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "auction_dollars": [{"draft_year": 2027, "amount": 5.00}],
                    },
                    {
                        "team_name": "Team Bob",
                        "auction_dollars": [{"draft_year": 2027, "amount": -5.00}],
                    },
                ],
                "conditions": [],
            },
            {
                "id": "t-2",
                "date": "2026-10-05T12:00:00Z",
                "agreement_season": 2026,
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "auction_dollars": [{"draft_year": 2028, "amount": 10.00}],
                    },
                    {
                        "team_name": "Team Bob",
                        "auction_dollars": [{"draft_year": 2028, "amount": -10.00}],
                    },
                ],
                "conditions": [],
            },
        ],
    }

    raw_bytes = json.dumps(ledger_content).encode("utf-8")
    body = json.dumps({"sha": "sha1", "content": base64.b64encode(raw_bytes).decode("ascii")})

    api = api_factory(mock_handler=lambda req: httpx.Response(200, text=body))
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )
    sync_resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/sync")
    assert sync_resp.status_code == 200
    assert sync_resp.json()["trades_synced"] == 2

    # Filter by draft year 2027
    resp_27 = api.client.get(f"/api/v1/leagues/{league_id}/trades?draft_year=2027")
    assert resp_27.status_code == 200
    assert len(resp_27.json()["trades"]) == 1
    assert resp_27.json()["trades"][0]["external_trade_id"] == "t-1"

    # Filter by draft year 2028
    resp_28 = api.client.get(f"/api/v1/leagues/{league_id}/trades?draft_year=2028")
    assert resp_28.status_code == 200
    assert len(resp_28.json()["trades"]) == 1
    assert resp_28.json()["trades"][0]["external_trade_id"] == "t-2"

    # Filter by non-existent year
    resp_29 = api.client.get(f"/api/v1/leagues/{league_id}/trades?draft_year=2029")
    assert resp_29.status_code == 200
    assert len(resp_29.json()["trades"]) == 0

    # Re-ingest with updated note on t-1
    ledger_content["active_trades"][0]["notes"] = "Updated summary notes"
    raw_bytes2 = json.dumps(ledger_content).encode("utf-8")
    body2 = json.dumps({"sha": "sha2", "content": base64.b64encode(raw_bytes2).decode("ascii")})

    # Wait or bypass rate limit for second sync: rebuild client with fresh clock or handler
    # Since api_factory mock_handler is fixed per build, test re-ingest directly on service
    with api.factory() as session:
        from unittest.mock import Mock

        fake_client = Mock(spec=httpx.Client)
        fake_client.get.return_value = httpx.Response(200, text=body2)
        service = TradeSyncService(session, http_client=fake_client)
        # Advance clock or mock rate limiter
        service._rate_limiter = Mock()
        service._rate_limiter.check.return_value = Mock(allowed=True, retry_after=0)
        from app.services.league_models import LeagueUser

        caller = LeagueUser(user_id=admin_id, role="admin")
        res = service.sync_trade_repo(caller, league_id)
        assert res.trades_synced == 2
        service.commit()

    # Verify updated notes on t-1
    trades_resp = api.client.get(f"/api/v1/leagues/{league_id}/trades")
    t1 = next(t for t in trades_resp.json()["trades"] if t["external_trade_id"] == "t-1")
    assert t1["summary"] == "Updated summary notes"

    # Verify deltas did NOT double after re-ingest (Finding 1 regression check)
    b_resp = api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027")
    assert b_resp.status_code == 200
    projs = {p["team_id"]: p for p in b_resp.json()["projections"]}
    assert projs["Team Alice"]["base_trade_delta"] == "5.00"
    assert projs["Team Bob"]["base_trade_delta"] == "-5.00"


def test_sync_rejects_unbalanced_zero_sum_ledger(api_factory: Callable[..., Api]) -> None:
    # Build unbalanced ledger where Alice gets $5 but Bob only gives $4 (sum != 0)
    unbalanced_ledger = {
        "version": 1,
        "active_trades": [
            {
                "id": "unbalanced-trade",
                "date": "2026-10-01T12:00:00Z",
                "agreement_season": 2026,
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "auction_dollars": [{"draft_year": 2027, "amount": 5.00}],
                    },
                    {
                        "team_name": "Team Bob",
                        "auction_dollars": [{"draft_year": 2027, "amount": -4.00}],
                    },
                ],
            }
        ],
    }
    raw_bytes = json.dumps(unbalanced_ledger).encode("utf-8")
    body = json.dumps({"sha": "sha-bad", "content": base64.b64encode(raw_bytes).decode("ascii")})

    api = api_factory(mock_handler=lambda req: httpx.Response(200, text=body))
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )
    sync_resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/sync")
    # Sync fails with 502 Bad Gateway due to zero-sum format error
    assert sync_resp.status_code == 502
    err_detail = sync_resp.json()["detail"]
    assert err_detail["code"] == "github_sync_failed"
    assert "fails zero-sum balance" in err_detail["message"]

    # Verify no invalid trade records were persisted
    trades_resp = api.client.get(f"/api/v1/leagues/{league_id}/trades")
    assert trades_resp.status_code == 200
    assert len(trades_resp.json()["trades"]) == 0


def test_settled_trades_conditions_ignored_in_active_budget(
    api_factory: Callable[..., Api],
) -> None:
    # Build ledger with one active trade and one settled trade with fulfilled condition
    ledger_content = {
        "version": 1,
        "settled_trade_ids": ["trade-settled-1"],
        "active_trades": [
            {
                "id": "trade-settled-1",
                "date": "2025-10-01T12:00:00Z",
                "agreement_season": 2025,
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "auction_dollars": [{"draft_year": 2026, "amount": 10.00}],
                    },
                    {
                        "team_name": "Team Bob",
                        "auction_dollars": [{"draft_year": 2026, "amount": -10.00}],
                    },
                ],
                "conditions": [
                    {
                        "id": "c-settled",
                        "draft_year": 2027,
                        "paying_team": "Team Bob",
                        "receiving_team": "Team Alice",
                        "amount": 25.00,
                        "status": "fulfilled",
                    }
                ],
            },
            {
                "id": "trade-active-2",
                "date": "2026-10-01T12:00:00Z",
                "agreement_season": 2026,
                "parties": [
                    {
                        "team_name": "Team Alice",
                        "auction_dollars": [{"draft_year": 2027, "amount": 5.00}],
                    },
                    {
                        "team_name": "Team Bob",
                        "auction_dollars": [{"draft_year": 2027, "amount": -5.00}],
                    },
                ],
                "conditions": [],
            },
        ],
    }

    raw_bytes = json.dumps(ledger_content).encode("utf-8")
    body = json.dumps(
        {
            "sha": "sha-settled",
            "content": base64.b64encode(raw_bytes).decode("ascii"),
        }
    )

    api = api_factory(mock_handler=lambda req: httpx.Response(200, text=body))
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )
    sync_resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/sync")
    assert sync_resp.status_code == 200

    # Query 2027 auction budget:
    # trade-settled-1 is settled, so its 25.00 condition must NOT be applied to 2027
    # Only trade-active-2 (5.00 delta) applies
    b_resp = api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027")
    assert b_resp.status_code == 200
    projs = {p["team_id"]: p for p in b_resp.json()["projections"]}
    assert projs["Team Alice"]["base_trade_delta"] == "5.00"
    assert projs["Team Alice"]["fulfilled_conditional_delta"] == "0.00"
    assert projs["Team Alice"]["projected_budget"] == "205.00"


def test_alias_cycle_defense(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # Set mutually circular aliases ("Team A" -> "Team B", "Team B" -> "Team A")
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "team_aliases": {"Alpha": "Beta", "Beta": "Alpha"},
        },
    )

    # Budget resolution does not loop infinitely
    resp = api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027")
    assert resp.status_code == 200


def test_discord_sync_trigger_accepted_and_mutex_lock(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # Configure trade tracker with discord_channel_id
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={"enabled": True, "discord_channel_id": "123456789"},
    )

    # First trigger succeeds with 202 Accepted
    resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/discord-sync")
    assert resp.status_code == 202
    body = resp.json()
    assert body["league_id"] == league_id
    assert body["status"] == "started"

    # Concurrent trigger while running returns 409 Conflict
    with api.factory() as session:
        from app.db.models import LeagueTradeConfig

        cfg = session.scalar(
            select(LeagueTradeConfig).where(LeagueTradeConfig.league_id == league_id)
        )
        assert cfg is not None
        cfg.discord_sync_status = "running"
        session.commit()

    resp_conflict = api.client.post(f"/api/v1/leagues/{league_id}/trades/discord-sync")
    assert resp_conflict.status_code == 409
    assert resp_conflict.json()["detail"]["code"] == "discord_sync_in_progress"

    # Complete background sync
    with api.factory() as session:
        service = TradeSyncService(session)
        service.complete_discord_sync(league_id, success=True)
        session.commit()

    # Verify status in config view
    cfg_resp = api.client.get(f"/api/v1/leagues/{league_id}/trade-config")
    assert cfg_resp.status_code == 200
    cfg_data = cfg_resp.json()
    assert cfg_data["discord_sync_status"] == "success"
    assert cfg_data["last_discord_sync_at"] is not None


def test_discord_sync_authorization_and_validation(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    member_id = create_user(api, "member@example.com", league_id=league_id, role="member")
    outsider_id = create_user(api, "outsider@example.com", league_id=None, role="member")

    sync_path = f"/api/v1/leagues/{league_id}/trades/discord-sync"

    # Disabled -> 400
    login(api, admin_id)
    resp_disabled = api.client.post(sync_path)
    assert resp_disabled.status_code == 400
    assert resp_disabled.json()["detail"]["code"] == "trade_tracker_disabled"

    # Missing channel ID -> 400
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
        },
    )
    resp_no_chan = api.client.post(sync_path)
    assert resp_no_chan.status_code == 400
    assert "channel ID" in resp_no_chan.json()["detail"]["message"]

    # Member -> 403 Forbidden
    login(api, member_id)
    assert api.client.post(sync_path).status_code == 403

    # Outsider -> 404 Not Found
    login(api, outsider_id)
    assert api.client.post(sync_path).status_code == 404


def test_run_discord_sync_job_worker_execution(
    api_factory: Callable[..., Api], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from typing import Any

    from app.config import _REPO_ROOT

    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # Configure channel ID and repo
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "discord_channel_id": "999888",
            "repo_owner": "bberk",
            "repo_name": "whodat-trades",
        },
    )

    # Configure bot token in settings
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENCODE_MODEL", "opencode-custom")
    get_settings.cache_clear()

    calls: list[dict[str, Any]] = []

    def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="Success", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with api.factory() as session:
        service = TradeSyncService(session)
        service.run_discord_sync_job(league_id)
        session.commit()

    assert len(calls) == 1
    call = calls[0]
    assert call["cmd"][1:3] == ["-m", "scripts.trade_agent.discord_trade_ingest"]
    assert "--channel-id" in call["cmd"]
    assert call["cmd"][call["cmd"].index("--channel-id") + 1] == "999888"
    assert "--repo" in call["cmd"]
    assert call["cmd"][call["cmd"].index("--repo") + 1] == "bberk/whodat-trades"
    assert call["cwd"] == str(_REPO_ROOT)
    assert call["env"]["PYTHONPATH"] == str(_REPO_ROOT)
    assert call["env"]["DISCORD_BOT_TOKEN"] == "fake-bot-token"
    assert call["env"]["OPENCODE_MODEL"] == "opencode-custom"

    # Status should be success
    cfg_resp = api.client.get(f"/api/v1/leagues/{league_id}/trade-config")
    assert cfg_resp.json()["discord_sync_status"] == "success"

    # Now test failure with CalledProcessError
    def mock_run_error(cmd: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            output="",
            stderr="Discord API error: rate limit exceeded",
        )

    monkeypatch.setattr(subprocess, "run", mock_run_error)

    with api.factory() as session:
        service = TradeSyncService(session)
        service.run_discord_sync_job(league_id)
        session.commit()

    cfg_resp = api.client.get(f"/api/v1/leagues/{league_id}/trade-config")
    assert cfg_resp.json()["discord_sync_status"] == "error"
    assert "Discord API error: rate limit exceeded" in cfg_resp.json()["last_discord_sync_error"]


def test_sync_trade_repo_missing_repo_config_error(api_factory: Callable[..., Api]) -> None:
    """Sync fails cleanly if repository owner and name have not been configured."""
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # Enable without repo owner and name
    api.client.put(f"/api/v1/leagues/{league_id}/trade-config", json={"enabled": True})
    resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/sync")
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "github_sync_failed"
    assert "owner and name must be configured" in resp.json()["detail"]["message"]


def test_run_discord_sync_job_with_league_discord_token(
    api_factory: Callable[..., Api], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a per-league Discord token is configured, worker decrypts and uses it."""
    import subprocess
    from typing import Any

    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    # Configure per-league encrypted discord bot token
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "discord_channel_id": "777666",
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
            "discord_token": "league-specific-bot-token",
        },
    )

    # Server environment has a different token or none
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "global-fallback-token")
    get_settings.cache_clear()

    calls: list[dict[str, Any]] = []

    def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="Success", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with api.factory() as session:
        service = TradeSyncService(session)
        service.run_discord_sync_job(league_id)
        session.commit()

    assert len(calls) == 1
    call = calls[0]
    # Encrypted league token takes priority over global fallback
    assert call["env"]["DISCORD_BOT_TOKEN"] == "league-specific-bot-token"


def test_trade_config_owners_and_aliases_mapping(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    path = f"/api/v1/leagues/{league_id}/trade-config"
    resp = api.client.get(path)
    assert resp.status_code == 200
    data = resp.json()

    # Owners in the league are listed with their current team name
    assert "owners" in data
    owners = {o["display_name"]: o for o in data["owners"]}
    assert "Alice" in owners
    assert owners["Alice"]["current_team_name"] == "Team Alice"
    assert owners["Alice"]["aliases"] == []
    assert "Bob" in owners
    assert owners["Bob"]["current_team_name"] == "Team Bob"
    assert owners["Bob"]["aliases"] == []

    # Update aliases mapping to owners
    update_resp = api.client.put(
        path,
        json={
            "team_aliases": {
                "alice_discord": "Alice",
                "The Ace": "Alice",
                "@bob_discord": "Bob",
            }
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    updated_owners = {o["display_name"]: o for o in updated["owners"]}
    assert updated_owners["Alice"]["aliases"] == ["The Ace", "alice_discord"]
    assert updated_owners["Bob"]["aliases"] == ["@bob_discord"]


def test_auction_budget_uses_current_season_team_name(api_factory: Callable[..., Api]) -> None:
    # Build ledger with trade referencing an old historical team name and an alias
    ledger_content = {
        "version": 1,
        "active_trades": [
            {
                "id": "trade-2027-name-change",
                "date": "2026-11-07T12:00:00Z",
                "agreement_season": 2024,
                "parties": [
                    {
                        "team_name": "Old Team Alice 2024",
                        "auction_dollars": [{"draft_year": 2027, "amount": -10.00}],
                    },
                    {
                        "team_name": "Bobby Nickname",
                        "auction_dollars": [{"draft_year": 2027, "amount": 10.00}],
                    },
                ],
            }
        ],
    }
    encoded = base64.b64encode(json.dumps(ledger_content).encode()).decode()
    github_body = json.dumps({"content": encoded, "sha": "abc12345", "encoding": "base64"})

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "contents/ledger.json" in str(request.url):
            return httpx.Response(200, text=github_body)
        return httpx.Response(404, text='{"message": "Not Found"}')

    api = api_factory(mock_handler=mock_handler)
    league_id = seed_league(api)

    # Add historical team for Alice in season 2024
    with api.factory() as session:
        owner_a = session.scalar(select(Owner).where(Owner.display_name == "Alice"))
        assert owner_a is not None
        old_team = Team(
            league_id=league_id,
            season=2024,
            external_id="1-old",
            name="Old Team Alice 2024",
            owner_id=owner_a.id,
        )
        session.add(old_team)
        session.commit()

    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    member_id = create_user(api, "member@example.com", league_id=league_id, role="member")
    login(api, admin_id)

    # Configure alias for Bob and enable trade tracker
    api.client.put(
        f"/api/v1/leagues/{league_id}/trade-config",
        json={
            "enabled": True,
            "repo_owner": "custom-owner",
            "repo_name": "custom-trades",
            "team_aliases": {"Bobby Nickname": "Bob"},
        },
    )

    # Sync trade ledger
    sync_resp = api.client.post(f"/api/v1/leagues/{league_id}/trades/sync")
    assert sync_resp.status_code == 200

    # Query auction budgets as member
    login(api, member_id)
    budget_resp = api.client.get(f"/api/v1/leagues/{league_id}/auction-budgets?draft_year=2027")
    assert budget_resp.status_code == 200
    projections = budget_resp.json()["projections"]

    # Table rows MUST use the current 2026 team names: "Team Alice" and "Team Bob"
    team_ids = [p["team_id"] for p in projections]
    assert "Team Alice" in team_ids
    assert "Team Bob" in team_ids
    assert "Old Team Alice 2024" not in team_ids
    assert "Bobby Nickname" not in team_ids

    proj_map = {p["team_id"]: p for p in projections}
    assert proj_map["Team Alice"]["net_delta"] == "-10.00"
    assert proj_map["Team Alice"]["projected_budget"] == "190.00"
    assert proj_map["Team Bob"]["net_delta"] == "10.00"
    assert proj_map["Team Bob"]["projected_budget"] == "210.00"
