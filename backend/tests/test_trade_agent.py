"""Tests for Discord trade ingestion worker and post-draft settlement scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from scripts.trade_agent.discord_trade_ingest import (
    DiscordMessage,
    build_opencode_trade_prompt,
    extract_trades_from_text,
    fetch_discord_messages,
    save_trades_to_repo,
    update_ledger_with_trades,
    validate_trade_payload,
)
from scripts.trade_agent.settle_draft import (
    is_trade_fully_executed,
    settle_trades_in_ledger,
)


def test_fetch_discord_messages_parses_response() -> None:
    raw_payload = [
        {
            "id": "1001",
            "content": "Trade: Alice gives Mahomes to Bob for Jefferson and $5 in 2027",
            "timestamp": "2026-11-07T12:00:00.000Z",
            "author": {"id": "user1", "username": "alice"},
        },
        {
            "id": "1002",
            "content": "Accept trade!",
            "timestamp": "2026-11-07T12:05:00.000Z",
            "author": {"id": "user2", "username": "bob"},
        },
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "channels/999/messages" in str(request.url)
        assert request.headers["authorization"] == "Bot test-token"
        return httpx.Response(200, json=raw_payload)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    messages = fetch_discord_messages("999", "test-token", http_client=client)

    assert len(messages) == 2
    assert messages[0].id == "1001"
    assert messages[0].author_username == "alice"
    assert messages[0].jump_url == "https://discord.com/channels/@me/999/1001"
    assert messages[1].id == "1002"
    assert messages[1].author_username == "bob"


def test_build_opencode_trade_prompt() -> None:
    msgs = [
        DiscordMessage(
            id="1",
            channel_id="99",
            author_id="a1",
            author_username="alice",
            content="Alice trades Mahomes to Bob",
            timestamp=datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
            jump_url="https://discord.com/1",
        )
    ]
    prompt = build_opencode_trade_prompt(msgs)
    assert "MESSAGES:" in prompt
    assert "@alice (ID: 1): Alice trades Mahomes to Bob" in prompt
    assert "Every trade MUST be zero-sum" in prompt


def test_extract_trades_from_yaml_code_block() -> None:
    model_output = """Here is the extracted trade:

```yaml
id: "trade-2027-1"
date: "2026-11-07T16:00:00Z"
agreement_season: 2026
source:
  jump_url: "https://discord.com/1"
parties:
  - team_name: "Team Alice"
    discord_user: "alice"
    players_sent:
      - name: "Patrick Mahomes"
    players_received:
      - name: "Justin Jefferson"
    draft_picks_sent: []
    draft_picks_received: []
    auction_dollars:
      - draft_year: 2027
        amount: -5.00
  - team_name: "Team Bob"
    discord_user: "bob"
    players_sent:
      - name: "Justin Jefferson"
    players_received:
      - name: "Patrick Mahomes"
    draft_picks_sent: []
    draft_picks_received: []
    auction_dollars:
      - draft_year: 2027
        amount: 5.00
conditions: []
notes: "Mahomes for Jefferson and $5"
```
"""
    trades = extract_trades_from_text(model_output)
    assert len(trades) == 1
    t = trades[0]
    assert t["id"] == "trade-2027-1"
    assert len(t["parties"]) == 2
    validate_trade_payload(t)


def test_validate_trade_payload_enforces_zero_sum() -> None:
    bad_trade: dict[str, Any] = {
        "id": "bad-1",
        "parties": [
            {
                "team_name": "A",
                "auction_dollars": [{"draft_year": 2027, "amount": -5.00}],
            },
            {
                "team_name": "B",
                "auction_dollars": [{"draft_year": 2027, "amount": 4.00}],  # Net -1.00!
            },
        ],
    }
    with pytest.raises(ValueError, match="not zero-sum"):
        validate_trade_payload(bad_trade)


def test_update_ledger_and_save_to_repo(tmp_path: Path) -> None:
    trade1 = {
        "id": "t1",
        "date": "2026-11-01T12:00:00Z",
        "agreement_season": 2026,
        "parties": [
            {"team_name": "Team A", "auction_dollars": [{"draft_year": 2027, "amount": 5.00}]},
            {"team_name": "Team B", "auction_dollars": [{"draft_year": 2027, "amount": -5.00}]},
        ],
        "conditions": [],
    }

    trade2 = {
        "id": "t2",
        "date": "2026-11-05T12:00:00Z",
        "agreement_season": 2026,
        "parties": [
            {"team_name": "Team A", "auction_dollars": [{"draft_year": 2028, "amount": 10.00}]},
            {"team_name": "Team B", "auction_dollars": [{"draft_year": 2028, "amount": -10.00}]},
        ],
        "conditions": [],
    }

    ledger: dict[str, Any] = {"version": 1, "active_trades": [trade1]}
    updated = update_ledger_with_trades(ledger, [trade2])
    assert len(updated["active_trades"]) == 2
    assert updated["active_trades"][0]["id"] == "t1"
    assert updated["active_trades"][1]["id"] == "t2"

    # Save to mock repo directory
    written = save_trades_to_repo(tmp_path, [trade1, trade2])
    assert len(written) == 3  # 2 trade files + 1 ledger.json
    assert (tmp_path / "trades" / "2026" / "2026-11-01-t1.yml").exists()
    assert (tmp_path / "trades" / "2026" / "2026-11-05-t2.yml").exists()
    assert (tmp_path / "ledger.json").exists()


def test_settle_draft_moves_executed_trades() -> None:
    # Trade 1: agreed in 2025, 2026 draft dollars -> fully executed for settle_year=2026
    trade_concluded = {
        "id": "trade-2025-1",
        "agreement_season": 2025,
        "parties": [
            {"auction_dollars": [{"draft_year": 2026, "amount": 5.00}]},
            {"auction_dollars": [{"draft_year": 2026, "amount": -5.00}]},
        ],
        "conditions": [],
    }

    # Trade 2: agreed in 2026, but has 2027 draft dollars -> NOT executed for settle_year=2026
    trade_future = {
        "id": "trade-2026-2",
        "agreement_season": 2026,
        "parties": [
            {"auction_dollars": [{"draft_year": 2027, "amount": 10.00}]},
            {"auction_dollars": [{"draft_year": 2027, "amount": -10.00}]},
        ],
        "conditions": [],
    }

    assert is_trade_fully_executed(trade_concluded, settle_year=2026) is True
    assert is_trade_fully_executed(trade_future, settle_year=2026) is False

    ledger = {
        "version": 1,
        "settle_through_year": 2025,
        "settled_trade_ids": ["old-trade"],
        "active_trades": [trade_concluded, trade_future],
    }

    updated = settle_trades_in_ledger(ledger, settle_year=2026)
    assert updated["settle_through_year"] == 2026
    assert "trade-2025-1" in updated["settled_trade_ids"]
    assert "old-trade" in updated["settled_trade_ids"]
    assert len(updated["active_trades"]) == 1
    assert updated["active_trades"][0]["id"] == "trade-2026-2"
