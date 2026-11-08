#!/usr/bin/env python3
"""Verify trade repo schema, zero-sum financial balances, and ledger consistency.

Rules enforced:
1. Every trade file in trades/ must be valid YAML.
2. Zero-sum auction dollars: For every trade and draft year, the sum of auction dollars
   across all parties must equal 0.00.
3. Matching draft picks: For every draft year and round, picks sent must match picks received.
4. Unique trade IDs and source message IDs across all trade files.
5. ledger.json consistency: active_trades must match all non-settled trades in trades/.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def verify_trade(path: Path, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    trade_id = data.get("id")
    if not trade_id:
        errors.append(f"{path}: Missing 'id'")

    parties = data.get("parties", [])
    if not isinstance(parties, list) or len(parties) < 2:
        errors.append(f"{path}: Trade must have at least 2 parties")
        return errors

    # Check zero-sum auction dollars per draft year
    dollar_balances: dict[int, Decimal] = {}
    for p in parties:
        for dollar_entry in p.get("auction_dollars", []):
            year = dollar_entry.get("draft_year")
            amount = dollar_entry.get("amount")
            if year is None or amount is None:
                errors.append(f"{path}: Invalid auction dollar entry: {dollar_entry}")
                continue
            delta = Decimal(str(amount))
            dollar_balances[year] = dollar_balances.get(year, Decimal("0.00")) + delta

    for year, bal in dollar_balances.items():
        if bal != Decimal("0.00"):
            errors.append(
                f"{path}: Auction dollars for draft year {year} are not zero-sum: total is {bal}"
            )

    # Check draft picks balance
    picks_sent: list[tuple[int, int]] = []
    picks_received: list[tuple[int, int]] = []
    for p in parties:
        for pick in p.get("draft_picks_sent", []):
            if "draft_year" in pick and "round" in pick:
                picks_sent.append((pick["draft_year"], pick["round"]))
        for pick in p.get("draft_picks_received", []):
            if "draft_year" in pick and "round" in pick:
                picks_received.append((pick["draft_year"], pick["round"]))

    if sorted(picks_sent) != sorted(picks_received):
        errors.append(
            f"{path}: Draft picks sent {picks_sent} do not match received {picks_received}"
        )

    return errors


def verify_repo(root: Path) -> int:
    errors: list[str] = []
    trade_files = sorted(glob.glob(str(root / "trades" / "**" / "*.yaml"), recursive=True))
    seen_ids: dict[str, Path] = {}
    seen_message_ids: dict[str, Path] = {}
    trades_by_id: dict[str, dict[str, Any]] = {}

    for file_str in trade_files:
        path = Path(file_str)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
        except Exception as e:
            errors.append(f"{path}: Failed to parse YAML: {e}")
            continue

        if not isinstance(content, dict):
            errors.append(f"{path}: Content must be a YAML mapping")
            continue

        t_id = content.get("id")
        if t_id:
            if t_id in seen_ids:
                errors.append(f"{path}: Duplicate trade id '{t_id}' (first in {seen_ids[t_id]})")
            else:
                seen_ids[t_id] = path
                trades_by_id[t_id] = content

        source = content.get("source", {})
        if isinstance(source, dict):
            msg_id = source.get("message_id")
            if msg_id:
                if msg_id in seen_message_ids:
                    errors.append(
                        f"{path}: Duplicate message_id '{msg_id}' (first in "
                        f"{seen_message_ids[msg_id]})"
                    )
                else:
                    seen_message_ids[msg_id] = path

        errors.extend(verify_trade(path, content))

    # Verify ledger.json if present
    ledger_path = root / "ledger.json"
    if ledger_path.exists():
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                ledger = json.load(f)
        except Exception as e:
            errors.append(f"ledger.json: Failed to parse JSON: {e}")
        else:
            settled_ids = set(ledger.get("settled_trade_ids", []))
            active_trades = ledger.get("active_trades", [])
            active_ids: set[str] = set()

            for at in active_trades:
                at_id = at.get("id")
                if not at_id:
                    errors.append("ledger.json: Active trade missing 'id'")
                    continue
                if at_id in settled_ids:
                    errors.append(
                        f"ledger.json: Trade '{at_id}' is in both active_trades and "
                        f"settled_trade_ids"
                    )
                if at_id in active_ids:
                    errors.append(f"ledger.json: Duplicate trade '{at_id}' in active_trades")
                active_ids.add(at_id)

                if at_id not in trades_by_id:
                    errors.append(
                        f"ledger.json: Active trade '{at_id}' does not exist as a YAML "
                        f"file in trades/"
                    )

            # Ensure all parsed trades in trades/ are accounted for
            for t_id in trades_by_id:
                if t_id not in active_ids and t_id not in settled_ids:
                    errors.append(
                        f"ledger.json: Trade '{t_id}' exists in trades/ but is missing from "
                        f"both active_trades and settled_trade_ids"
                    )

    if errors:
        print(f"FAILED: Found {len(errors)} validation error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"SUCCESS: Verified {len(trade_files)} trade file(s). All zero-sum rules and schemas pass."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify trade repository consistency.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root directory of trade repository (default: current directory)",
    )
    args = parser.parse_args()
    sys.exit(verify_repo(args.root))


if __name__ == "__main__":
    main()
