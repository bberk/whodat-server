#!/usr/bin/env python3
"""Post-draft trade settlement script.

Archives trades that are fully executed through a target draft year:
- Moves trade IDs from active_trades to settled_trade_ids.
- Updates settle_through_year in ledger.json.
- Preserves all historical trade YAML files untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_trade_settled(trade: dict[str, Any], target_draft_year: int) -> bool:
    """Check if all assets and conditions in a trade are on or before target_draft_year."""
    # Check parties' auction dollars and draft picks
    for party in trade.get("parties", []):
        for dollar_entry in party.get("auction_dollars", []):
            year = dollar_entry.get("draft_year")
            if year and year > target_draft_year:
                return False
        for pick in party.get("draft_picks_sent", []):
            year = pick.get("draft_year")
            if year and year > target_draft_year:
                return False
        for pick in party.get("draft_picks_received", []):
            year = pick.get("draft_year")
            if year and year > target_draft_year:
                return False

    # Check conditions
    for cond in trade.get("conditions", []):
        year = cond.get("draft_year")
        if year and year > target_draft_year:
            return False
        # If a condition is still pending for <= target_draft_year,
        # it cannot be automatically settled
        status = str(cond.get("status", "pending")).lower()
        if status == "pending":
            return False

    return True


def settle_draft(root: Path, draft_year: int) -> int:
    ledger_path = root / "ledger.json"
    if not ledger_path.exists():
        print(f"Error: {ledger_path} not found.", file=sys.stderr)
        return 1

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    current_settled = set(ledger.get("settled_trade_ids", []))
    active_trades = ledger.get("active_trades", [])

    new_active: list[dict[str, Any]] = []
    settled_now: list[str] = []

    for trade in active_trades:
        t_id = trade.get("id")
        if not t_id:
            continue
        if is_trade_settled(trade, draft_year):
            settled_now.append(t_id)
            current_settled.add(t_id)
        else:
            new_active.append(trade)

    ledger["settle_through_year"] = max(draft_year, ledger.get("settle_through_year", 0))
    ledger["settled_trade_ids"] = sorted(list(current_settled))
    ledger["active_trades"] = new_active
    ledger["last_compiled_at"] = datetime.now(timezone.utc).isoformat()

    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Settled {len(settled_now)} trade(s) through draft year {draft_year}:")
    for t in settled_now:
        print(f"  - {t}")
    print(f"Remaining active trades in ledger: {len(new_active)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle trades through a draft year.")
    parser.add_argument(
        "--draft-year",
        type=int,
        required=True,
        help="Draft year completed (e.g. 2026)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root directory of trade repository (default: current directory)",
    )
    args = parser.parse_args()
    sys.exit(settle_draft(args.root, args.draft_year))


if __name__ == "__main__":
    main()
