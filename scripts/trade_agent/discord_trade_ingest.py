"""Discord trade ingest worker for extracting announced fantasy football trades.

Fetches messages from a Discord trade announcements channel, extracts structured trade
records using an LLM / OpenCode prompt, updates the git trade repository with trade YAMLs
and a compiled ledger.json, and opens a GitHub pull request for league review.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml  # type: ignore[import-untyped]

_LOG = logging.getLogger(__name__)

TRADE_PROMPT_TEMPLATE = """You are an expert fantasy football trade extraction agent.
Analyze the following Discord trade announcement messages and extract structured trade data.

MESSAGES:
{messages_text}

For each trade, produce a YAML record with the following EXACT format:
```yaml
id: "<unique-kebab-id-e.g.-trade-2027-1>"
date: "<ISO8601-date-e.g.-2026-11-07T16:00:00Z>"
agreement_season: <integer-season-e.g.-2026>
source:
  jump_url: "<discord-message-jump-url>"
parties:
  - team_name: "<Team A name or owner name>"
    discord_user: "<username-without-@>"
    players_sent:
      - name: "<Player Name>"
    players_received:
      - name: "<Player Name>"
    draft_picks_sent:
      - draft_year: <year>
        round: <round_number>
    draft_picks_received: []
    auction_dollars:
      - draft_year: <year>
        amount: <-amount-sent-e.g.--5.00>
  - team_name: "<Team B name or owner name>"
    discord_user: "<username-without-@>"
    players_sent: []
    players_received:
      - name: "<Player Name>"
    draft_picks_sent: []
    draft_picks_received:
      - draft_year: <year>
        round: <round_number>
    auction_dollars:
      - draft_year: <year>
        amount: <+amount-received-e.g.-5.00>
conditions:
  - id: "<condition-id>"
    description: "<Description of condition>"
    draft_year: <year>
    paying_team: "<Team paying if condition met>"
    receiving_team: "<Team receiving if condition met>"
    amount: <amount>
    status: "pending" # or "fulfilled" or "void"
notes: "<Brief human-readable summary of the trade>"
```

RULES:
1. Every trade MUST be zero-sum for auction dollars in each draft year:
   sum of party deltas for that year must be 0.
2. Sending auction dollars is negative (e.g. -5.00), receiving is positive (e.g. 5.00).
3. If no auction dollars or picks are exchanged, provide empty lists `[]`.
4. Output YAML code blocks ONLY.
"""


@dataclass(frozen=True)
class DiscordMessage:
    """A Discord chat message from a trade channel."""

    id: str
    channel_id: str
    author_id: str
    author_username: str
    content: str
    timestamp: datetime
    jump_url: str


def fetch_discord_messages(
    channel_id: str,
    bot_token: str,
    *,
    after_message_id: str | None = None,
    limit: int = 100,
    http_client: httpx.Client | None = None,
) -> list[DiscordMessage]:
    """Fetch recent messages from a Discord channel using the bot API token."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if after_message_id:
        params["after"] = after_message_id

    headers = {
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "whodat-server-trade-agent/1.0",
    }

    client = http_client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(url, headers=headers, params=params)
    finally:
        if http_client is None:
            client.close()

    if resp.status_code != 200:
        raise RuntimeError(f"Discord API returned status {resp.status_code}: {resp.text}")

    payload = resp.json()
    messages: list[DiscordMessage] = []
    for msg in payload:
        ts_str = msg.get("timestamp", "")
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str) if ts_str else datetime.now(UTC)
        author = msg.get("author", {})
        msg_id = str(msg["id"])
        messages.append(
            DiscordMessage(
                id=msg_id,
                channel_id=channel_id,
                author_id=str(author.get("id", "")),
                author_username=str(author.get("username", "")),
                content=str(msg.get("content", "")),
                timestamp=dt,
                jump_url=f"https://discord.com/channels/@me/{channel_id}/{msg_id}",
            )
        )

    # Sort oldest first
    messages.sort(key=lambda m: m.timestamp)
    return messages


def build_opencode_trade_prompt(messages: list[DiscordMessage]) -> str:
    """Format Discord messages into the prompt template for trade extraction."""
    lines: list[str] = []
    for m in messages:
        dt_str = m.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"[{dt_str}] @{m.author_username} (ID: {m.id}): {m.content}")
        lines.append(f"Jump URL: {m.jump_url}")
        lines.append("-" * 40)
    messages_text = "\n".join(lines)
    return TRADE_PROMPT_TEMPLATE.format(messages_text=messages_text)


def extract_trades_from_text(raw_text: str) -> list[dict[str, Any]]:
    """Extract and parse YAML trade blocks from model output."""
    yaml_blocks = re.findall(r"```ya?ml\s*(.*?)\s*```", raw_text, flags=re.DOTALL)
    trades: list[dict[str, Any]] = []

    content_to_parse = yaml_blocks if yaml_blocks else [raw_text]
    for block in content_to_parse:
        block_clean = block.strip()
        if not block_clean:
            continue
        try:
            parsed = yaml.safe_load(block_clean)
            if isinstance(parsed, dict) and "id" in parsed and "parties" in parsed:
                trades.append(parsed)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "id" in item and "parties" in item:
                        trades.append(item)
        except yaml.YAMLError as exc:
            _LOG.warning("Failed to parse YAML block: %s", exc)

    return trades


def validate_trade_payload(trade: dict[str, Any]) -> None:
    """Ensure trade conforms to zero-sum rules and required fields."""
    if "id" not in trade:
        raise ValueError("Trade missing required 'id' field")
    ext_id = str(trade["id"])
    if not re.match(r"^[A-Za-z0-9_-]+$", ext_id):
        raise ValueError(
            f"Trade id {ext_id!r} is invalid: must only contain alphanumeric, dash, "
            "and underscore characters"
        )

    parties = trade.get("parties", [])
    if len(parties) < 2:
        raise ValueError(f"Trade {ext_id} must have at least 2 parties")

    year_sums: dict[int, Decimal] = {}
    for party in parties:
        for dollar_leg in party.get("auction_dollars", []):
            try:
                yr = int(dollar_leg["draft_year"])
                amt = Decimal(str(dollar_leg["amount"])).quantize(Decimal("0.01"))
            except Exception as exc:
                raise ValueError(f"Invalid dollar entry in trade {ext_id}: {exc}") from exc
            year_sums[yr] = year_sums.get(yr, Decimal("0.00")) + amt

    for yr, total in year_sums.items():
        if total != Decimal("0.00"):
            raise ValueError(
                f"Trade {ext_id} is not zero-sum for draft year {yr}: net sum is {total:.2f}"
            )


def update_ledger_with_trades(
    ledger_data: dict[str, Any], new_trades: list[dict[str, Any]]
) -> dict[str, Any]:
    """Append new trades to ledger.json, deduplicating by ID."""
    active_trades = list(ledger_data.get("active_trades", []))
    existing_ids = {str(t["id"]) for t in active_trades}

    for trade in new_trades:
        validate_trade_payload(trade)
        trade_id = str(trade["id"])
        if trade_id in existing_ids:
            # Replace existing trade with updated version
            active_trades = [t for t in active_trades if str(t["id"]) != trade_id]
        active_trades.append(trade)
        existing_ids.add(trade_id)

    # Sort trades chronologically
    active_trades.sort(key=lambda t: str(t.get("date", "")))

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": ledger_data.get("version", 1),
        "last_compiled_at": now_iso,
        "settle_through_year": ledger_data.get("settle_through_year", 2026),
        "settled_trade_ids": list(ledger_data.get("settled_trade_ids", [])),
        "active_trades": active_trades,
    }


def save_trades_to_repo(repo_dir: Path, trades: list[dict[str, Any]]) -> list[Path]:
    """Write individual trade YAML files and update ledger.json."""
    written_files: list[Path] = []
    trades_dir = repo_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    # Read current ledger
    ledger_path = repo_dir / "ledger.json"
    if ledger_path.exists():
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger_data = {
            "version": 1,
            "last_compiled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "settle_through_year": 2026,
            "settled_trade_ids": [],
            "active_trades": [],
        }

    # Write trade YAMLs
    for trade in trades:
        validate_trade_payload(trade)
        season = str(trade.get("agreement_season", 2026))
        season_dir = trades_dir / season
        season_dir.mkdir(parents=True, exist_ok=True)

        trade_date = str(trade.get("date", "2026-01-01"))[:10]
        trade_id = str(trade["id"])
        file_path = (season_dir / f"{trade_date}-{trade_id}.yml").resolve()
        if not file_path.is_relative_to(trades_dir.resolve()):
            raise ValueError(f"Path traversal detected in trade id {trade_id}")

        file_path.write_text(yaml.safe_dump(trade, sort_keys=False), encoding="utf-8")
        written_files.append(file_path)

    # Update ledger.json
    updated_ledger = update_ledger_with_trades(ledger_data, trades)
    ledger_path.write_text(json.dumps(updated_ledger, indent=2) + "\n", encoding="utf-8")
    written_files.append(ledger_path)

    return written_files


def run_ingest(
    channel_id: str,
    bot_token: str,
    repo_dir: Path | str,
    *,
    repo: str | None = None,
    opencode_runner: Callable[[str], str] | None = None,
    dry_run: bool = False,
    http_client: httpx.Client | None = None,
) -> int:
    """Orchestrate Discord fetch, LLM trade extraction, repo update, and PR opening."""
    repo_path = Path(repo_dir)

    _LOG.info("Fetching messages from Discord channel %s...", channel_id)
    messages = fetch_discord_messages(channel_id, bot_token, http_client=http_client)
    if not messages:
        _LOG.info("No messages found in Discord channel.")
        return 0

    prompt = build_opencode_trade_prompt(messages)

    if opencode_runner is None:
        raise RuntimeError("No OpenCode runner provided for LLM extraction")

    _LOG.info("Invoking OpenCode / LLM for trade extraction...")
    model_output = opencode_runner(prompt)

    trades = extract_trades_from_text(model_output)
    if not trades:
        _LOG.info("No trades identified in messages.")
        return 0

    _LOG.info("Extracted %d trades. Validating...", len(trades))
    for trade in trades:
        validate_trade_payload(trade)

    if dry_run:
        _LOG.info("Dry-run mode: printing extracted trades without git commit.")
        for t in trades:
            print(yaml.safe_dump(t, sort_keys=False))
        return len(trades)

    _LOG.info("Saving trades to repository at %s...", repo_path)
    written = save_trades_to_repo(repo_path, trades)
    _LOG.info("Wrote %d files: %s", len(written), [str(f.name) for f in written])

    # Git operations: branch, commit, PR
    branch_name = f"trade-sync-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    subprocess.run(["git", "-C", str(repo_path), "checkout", "-b", branch_name], check=True)
    subprocess.run(["git", "-C", str(repo_path), "add", "trades/", "ledger.json"], check=True)
    commit_msg = f"Sync {len(trades)} trade(s) from Discord\n\nAutomated trade ingestion."
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "-C", str(repo_path), "push", "-u", "origin", branch_name], check=True)

    pr_title = f"Sync {len(trades)} trade(s) from Discord"
    pr_body = (
        f"Automated trade ingestion from Discord channel `{channel_id}`.\n\n"
        f"Trades synced: {len(trades)}\n\n"
        "Please review the extracted players, draft picks, and auction dollar changes."
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
    subprocess.run(pr_cmd, check=True, cwd=str(repo_path))
    _LOG.info("Pull request opened successfully.")
    return len(trades)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest fantasy football trades from Discord.")
    parser.add_argument("--channel-id", required=True, help="Discord trade channel ID")
    parser.add_argument(
        "--repo-dir", default="./whodat-trades", help="Path to whodat-trades git repo"
    )
    parser.add_argument(
        "--repo", default=None, help="Target GitHub repo (owner/name); defaults to remote"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print extracted trades without git push"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN environment variable required")

    def run_opencode_cli(p: str) -> str:
        cmd = ["opencode", "run"]
        model = os.environ.get("OPENCODE_MODEL")
        if model:
            cmd.extend(["--model", model])
        cmd.append(p)
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout

    run_ingest(
        channel_id=args.channel_id,
        bot_token=token,
        repo_dir=Path(args.repo_dir),
        repo=args.repo,
        opencode_runner=run_opencode_cli,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
