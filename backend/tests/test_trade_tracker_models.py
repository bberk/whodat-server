"""Tests for trade tracker models, relationships, and cascade deletions."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    League,
    LeagueTrade,
    LeagueTradeBudgetDelta,
    LeagueTradeConfig,
    LeagueTradeParty,
    Owner,
    UserLeague,
)
from app.services.league_models import LeagueUser
from app.services.league_service import LeagueService


def _actor(user: AppUser) -> LeagueUser:
    return LeagueUser(user_id=user.id, role=user.role)


def test_trade_tracker_models_crud_and_relationships(db_session: Session) -> None:
    session = db_session
    now = datetime.now(UTC)

    # 1. Create league with trade tracker enabled
    league = League(
        provider="espn",
        external_id="trade_test_league_1",
        name="Trade League",
        league_metadata={},
        provider_config_ref="fake_ref",
        has_trades_enabled=True,
    )
    session.add(league)
    session.flush()

    assert league.has_trades_enabled is True

    # 2. Add owner
    owner = Owner(league_id=league.id, external_id="owner_1", display_name="Alice")
    session.add(owner)
    session.flush()

    # 3. Add trade config
    config = LeagueTradeConfig(
        league_id=league.id,
        enabled=True,
        discord_channel_id="123456789",
        repo_owner="bberk",
        repo_name="whodat-trades",
        branch="main",
        base_auction_budget=Decimal("200.00"),
        team_aliases={"alice_discord": owner.id},
    )
    session.add(config)
    session.flush()

    assert league.trade_config is not None
    assert league.trade_config.repo_name == "whodat-trades"
    assert league.trade_config.base_auction_budget == Decimal("200.00")
    assert league.trade_config.discord_sync_status == "idle"

    # 4. Add trade
    trade = LeagueTrade(
        league_id=league.id,
        external_trade_id="2026-11-07-trade-1",
        trade_date=now,
        agreement_season=2026,
        is_settled=False,
        discord_url="https://discord.com/channels/123/456/789",
        summary="Alice trades Mahomes for JJ",
        raw_yaml="version: 1\nid: 2026-11-07-trade-1\n",
        conditions=[
            {
                "id": "c1",
                "description": "If Mahomes MVP, +$5 in 2028",
                "draft_year": 2028,
                "amount": "5.00",
                "status": "pending",
            }
        ],
    )
    session.add(trade)
    session.flush()

    # 5. Add trade parties
    party_alice = LeagueTradeParty(
        trade_id=trade.id,
        league_id=league.id,
        owner_id=owner.id,
        franchise_key="espn:1",
        team_name_raw="Team Alice",
        players_sent=[{"name": "Patrick Mahomes", "pos": "QB"}],
        players_received=[{"name": "Justin Jefferson", "pos": "WR"}],
        draft_picks_sent=[{"draft_year": 2027, "round": 1}],
        draft_picks_received=[],
    )
    session.add(party_alice)
    session.flush()

    # 6. Add multi-year budget deltas
    delta_2027 = LeagueTradeBudgetDelta(
        party_id=party_alice.id,
        league_id=league.id,
        draft_year=2027,
        amount=Decimal("-5.00"),
    )
    delta_2028 = LeagueTradeBudgetDelta(
        party_id=party_alice.id,
        league_id=league.id,
        draft_year=2028,
        amount=Decimal("-10.00"),
    )
    session.add_all([delta_2027, delta_2028])
    session.flush()

    # Verify relationships and queries
    reloaded_league = session.get(League, league.id)
    assert reloaded_league is not None
    assert len(reloaded_league.trades) == 1
    assert reloaded_league.trades[0].external_trade_id == "2026-11-07-trade-1"

    reloaded_trade = reloaded_league.trades[0]
    assert len(reloaded_trade.parties) == 1
    reloaded_party = reloaded_trade.parties[0]
    assert reloaded_party.team_name_raw == "Team Alice"
    assert reloaded_party.owner_id == owner.id
    assert len(reloaded_party.budget_deltas) == 2
    assert [d.draft_year for d in reloaded_party.budget_deltas] == [2027, 2028]
    assert [d.amount for d in reloaded_party.budget_deltas] == [
        Decimal("-5.00"),
        Decimal("-10.00"),
    ]


def test_delete_league_cascades_trade_tracker_tables(db_session: Session) -> None:
    session = db_session
    now = datetime.now(UTC)

    # Setup admin user
    admin = AppUser(email="admin@example.com", password_hash="hash", role="admin")
    session.add(admin)
    session.flush()

    # Create doomed and survivor leagues
    doomed = League(
        provider="espn",
        external_id="doomed_trades_league",
        name="Doomed League",
        league_metadata={},
        provider_config_ref="fake_ref",
        has_trades_enabled=True,
    )
    survivor = League(
        provider="espn",
        external_id="survivor_trades_league",
        name="Survivor League",
        league_metadata={},
        provider_config_ref="fake_ref",
        has_trades_enabled=True,
    )
    session.add_all([doomed, survivor])
    session.flush()

    # Memberships
    session.add_all(
        [
            UserLeague(user_id=admin.id, league_id=doomed.id),
            UserLeague(user_id=admin.id, league_id=survivor.id),
        ]
    )
    session.flush()

    # Add trade data to both leagues
    for lg in (doomed, survivor):
        owner = Owner(league_id=lg.id, external_id=f"owner_{lg.id}", display_name="Owner")
        session.add(owner)
        session.flush()

        cfg = LeagueTradeConfig(
            league_id=lg.id,
            enabled=True,
            base_auction_budget=Decimal("200.00"),
            team_aliases={},
        )
        trade = LeagueTrade(
            league_id=lg.id,
            external_trade_id=f"trade_{lg.id}",
            trade_date=now,
            agreement_season=2026,
            is_settled=False,
            summary="Trade",
            raw_yaml="",
            conditions=[],
        )
        session.add_all([cfg, trade])
        session.flush()

        party = LeagueTradeParty(
            trade_id=trade.id,
            league_id=lg.id,
            owner_id=owner.id,
            team_name_raw="Team",
            players_sent=[],
            players_received=[],
            draft_picks_sent=[],
            draft_picks_received=[],
        )
        session.add(party)
        session.flush()

        delta = LeagueTradeBudgetDelta(
            party_id=party.id,
            league_id=lg.id,
            draft_year=2027,
            amount=Decimal("10.00"),
        )
        session.add(delta)
        session.flush()

    # Pre-condition: both leagues have rows
    for model in (LeagueTradeConfig, LeagueTrade, LeagueTradeParty, LeagueTradeBudgetDelta):
        count = session.scalar(select(func.count()).select_from(model))
        assert count == 2

    # Execute delete_league on doomed
    service = LeagueService(session, None, provider_id="fake")  # type: ignore[arg-type]
    service.delete_league(_actor(admin), doomed.id)
    service.commit()

    # Post-condition: doomed rows deleted, survivor rows completely preserved
    assert session.get(League, doomed.id) is None
    assert session.get(League, survivor.id) is not None

    for model in (LeagueTradeConfig, LeagueTrade, LeagueTradeBudgetDelta):
        doomed_count = session.scalar(
            select(func.count()).select_from(model).where(model.league_id == doomed.id)
        )
        assert doomed_count == 0

        survivor_count = session.scalar(
            select(func.count()).select_from(model).where(model.league_id == survivor.id)
        )
        assert survivor_count == 1

    # LeagueTradeParty is also cleaned up
    party_count = session.scalar(select(func.count()).select_from(LeagueTradeParty))
    assert party_count == 1
