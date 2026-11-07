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
from sqlalchemy import Engine, create_engine
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
    assert data["repo_owner"] == "bberk"
    assert data["repo_name"] == "whodat-trades"
    assert data["has_github_token"] is False
    assert data["base_auction_budget"] == "200.00"


def test_update_trade_config_and_token_encryption(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    league_id = seed_league(api)
    admin_id = create_user(api, "admin@example.com", league_id=league_id, role="admin")
    login(api, admin_id)

    path = f"/api/v1/leagues/{league_id}/trade-config"

    # Update config and set GitHub token
    update_payload = {
        "enabled": True,
        "discord_channel_id": "999888777",
        "repo_owner": "custom-owner",
        "repo_name": "custom-trades",
        "branch": "develop",
        "github_token": "ghp_secrettoken12345",
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
    assert data["base_auction_budget"] == "250.00"
    assert data["team_aliases"] == {"alice_tag": "Alice"}

    # Token is never returned in response body
    assert "ghp_secrettoken12345" not in resp.text

    # Verify encrypted in DB
    with api.factory() as session:
        cfg = session.query(LeagueTradeConfig).filter_by(league_id=league_id).one()
        assert cfg.github_token_encrypted is not None
        assert "ghp_secrettoken12345" not in cfg.github_token_encrypted

    # Clear token
    resp_clear = api.client.put(path, json={"clear_github_token": True})
    assert resp_clear.status_code == 200
    assert resp_clear.json()["has_github_token"] is False


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
    api.client.put(config_path, json={"enabled": True, "base_auction_budget": "200.00"})

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
    api.client.put(config_path, json={"enabled": True})

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

    api.client.put(f"/api/v1/leagues/{league_id}/trade-config", json={"enabled": True})
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
