"""Post-draft settle script for truncating executed trades in ledger.json.

After an annual league draft concludes, this script settles all trades whose draft years
and conditions are on or before the settled draft year, moving their IDs to settled_trade_ids
and removing them from active_trades to keep the active ledger compact. Historical trade
YAML files under trades/{season}/ are strictly preserved.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def is_trade_fully_executed(trade: dict[str, Any], settle_year: int) -> bool:
    """Check if all draft assets and conditions in a trade have concluded by settle_year."""
    # 1. Agreement season must be on or before settle_year
    agreement_season = int(trade.get("agreement_season", 0))
    if agreement_season > settle_year:
        return False

    # 2. Check parties: auction dollars and draft picks
    for party in trade.get("parties", []):
        for dollar in party.get("auction_dollars", []):
            if int(dollar.get("draft_year", 0)) > settle_year:
                return False
        for pick in party.get("draft_picks_sent", []):
            if int(pick.get("draft_year", 0)) > settle_year:
                return False
        for pick in party.get("draft_picks_received", []):
            if int(pick.get("draft_year", 0)) > settle_year:
                return False

    # 3. Check conditions
    for cond in trade.get("conditions", []):
        if int(cond.get("draft_year", 0)) > settle_year:
            return False

    return True


def settle_trades_in_ledger(ledger_data: dict[str, Any], settle_year: int) -> dict[str, Any]:
    """Return a new ledger data dictionary with trades concluded by settle_year settled."""
    active_trades = list(ledger_data.get("active_trades", []))
    settled_ids = set(ledger_data.get("settled_trade_ids", []))

    new_active_trades: list[dict[str, Any]] = []
    newly_settled: list[str] = []

    for trade in active_trades:
        trade_id = str(trade["id"])
        if is_trade_fully_executed(trade, settle_year):
            settled_ids.add(trade_id)
            newly_settled.append(trade_id)
        else:
            new_active_trades.append(trade)

    current_settle_through = int(ledger_data.get("settle_through_year", 2026))
    updated_settle_through = max(current_settle_through, settle_year)

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": ledger_data.get("version", 1),
        "last_compiled_at": now_iso,
        "settle_through_year": updated_settle_through,
        "settled_trade_ids": sorted(settled_ids),
        "active_trades": new_active_trades,
    }


def run_settle(
    repo_dir: Path | str,
    settle_year: int,
    *,
    repo: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Execute draft settlement on the ledger.json in repo_dir."""
    repo_path = Path(repo_dir)
    ledger_path = repo_path / "ledger.json"

    if not ledger_path.exists():
        raise FileNotFoundError(f"ledger.json not found at {ledger_path}")

    ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    initial_active_count = len(ledger_data.get("active_trades", []))

    updated_ledger = settle_trades_in_ledger(ledger_data, settle_year)
    remaining_active_count = len(updated_ledger["active_trades"])
    settled_count = initial_active_count - remaining_active_count

    _LOG.info(
        "Settlement for draft year %d: settled %d trade(s), %d active trade(s) remaining.",
        settle_year,
        settled_count,
        remaining_active_count,
    )

    if dry_run:
        _LOG.info("Dry-run mode: printing updated ledger preview.")
        print(json.dumps(updated_ledger, indent=2))
        return settled_count, remaining_active_count

    ledger_path.write_text(json.dumps(updated_ledger, indent=2) + "\n", encoding="utf-8")

    branch_name = f"settle-draft-{settle_year}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    subprocess.run(["git", "-C", str(repo_path), "checkout", "-b", branch_name], check=True)
    subprocess.run(["git", "-C", str(repo_path), "add", "ledger.json"], check=True)
    commit_msg = (
        f"Settle trades through {settle_year} draft\n\n"
        f"Moved {settled_count} concluded trades to settled_trade_ids."
    )
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "-C", str(repo_path), "push", "-u", "origin", branch_name], check=True)

    pr_title = f"Post-Draft Settle: {settle_year} draft concluded"
    pr_body = (
        f"Automated settlement for the {settle_year} draft.\n\n"
        f"- Trades settled: {settled_count}\n"
        f"- Active future trades remaining: {remaining_active_count}\n"
        f"- Historical trade YAML files in `trades/` are preserved."
    )
    pr_cmd = [
        "gh",
        "pr",
        "create",
        "--head",
        branch_name,
        "--title",
        pr_title,
        "--body",
        pr_body,
    ]
    if repo:
        pr_cmd.extend(["--repo", repo])
    subprocess.run(pr_cmd, check=True)
    _LOG.info("Settlement pull request created.")
    return settled_count, remaining_active_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle trades concluded by a given draft year.")
    parser.add_argument(
        "--settle-year", type=int, required=True, help="Concluded draft year to settle"
    )
    parser.add_argument(
        "--repo-dir", default="./whodat-trades", help="Path to whodat-trades git repo"
    )
    parser.add_argument(
        "--repo", default=None, help="Target GitHub repo (owner/name); defaults to remote"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print updated ledger without committing"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run_settle(
        repo_dir=Path(args.repo_dir),
        settle_year=args.settle_year,
        repo=args.repo,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
