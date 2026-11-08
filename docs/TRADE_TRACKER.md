# Trade Tracker & Projected Auction Bucks Runbook

This document details the architecture, configuration, operation, and maintenance of the Trade Tracker and Projected Auction Bucks feature in Whodat Server.

---

## 1. Architectural Overview

The Trade Tracker connects three decoupled systems to maintain an auditable, version-controlled trade ledger and compute projected auction dollars for future fantasy drafts:

```
[ Discord #trades ]
        │
        ▼ (Message extraction via Discord Bot)
[ OpenCode Trade Agent ] (Whodat Server sidecar / worker)
        │
        ▼ (Opens Pull Request with trade YAML + updated ledger)
[ GitHub Trade Repo ] (e.g. bberk/whodat-trades)
        │
        ▼ (Merged after human league review)
[ Whodat Server Ingestion ] (Reads ledger.json via GitHub API)
        │
        ▼ (Computes exact budget projections via Domain Engine)
[ Whodat Frontend ] (Projected Auction Bucks Table + Trade Log Feed)
```

1. **Discord `#trades` Channel**: The source of truth for announced trades among league members.
2. **Trade Repository (`owner/repo`)**: A private or public GitHub repository holding individual YAML trade records and a compiled `ledger.json`.
3. **Whodat Server**:
   - Manages encrypted league credentials (GitHub PAT).
   - Ingests `ledger.json` from GitHub.
   - Computes deterministic, exact auction budgets using `Decimal` arithmetic.
   - Displays real-time standings and trade history on `/leagues/:id/trades`.

---

## 2. Trade Repository Schema

A template repository is provided in `docs/trade-repo-template/`.

### 2.1 Directory Structure

```
├── .github/workflows/
│   ├── verify-ledger.yml       # CI zero-sum balance and schema verification
│   └── settle-draft.yml        # Manual workflow to archive settled trades post-draft
├── scripts/
│   ├── verify_ledger.py        # Python zero-sum validator
│   └── settle_draft.py         # Python draft settlement script
├── trades/
│   └── <season>/               # Directory per agreement season (e.g. 2026/)
│       └── trade-*.yaml        # Individual trade YAML records
└── ledger.json                 # Consolidated active trades and settled trade IDs
```

### 2.2 Individual Trade YAML Schema (`trades/YYYY/trade-*.yaml`)

```yaml
id: "trade-2026-001"
date: "2026-11-07T16:00:00Z"
agreement_season: 2026
source:
  channel_id: "123456789012345678"
  message_id: "987654321098765432"
  jump_url: "https://discord.com/channels/123/456/789"
parties:
  - team_name: "Team Alice"
    discord_user: "alice_ff"
    players_sent:
      - name: "Patrick Mahomes"
        position: "QB"
    players_received:
      - name: "Justin Jefferson"
        position: "WR"
    draft_picks_sent:
      - draft_year: 2027
        round: 1
    draft_picks_received: []
    auction_dollars:
      - draft_year: 2027
        amount: -5.00
      - draft_year: 2028
        amount: -10.00
  - team_name: "Team Bob"
    discord_user: "bob_commish"
    players_sent:
      - name: "Justin Jefferson"
        position: "WR"
    players_received:
      - name: "Patrick Mahomes"
        position: "QB"
    draft_picks_sent: []
    draft_picks_received:
      - draft_year: 2027
        round: 1
    auction_dollars:
      - draft_year: 2027
        amount: 5.00
      - draft_year: 2028
        amount: 10.00
conditions:
  - id: "c1"
    description: "If Patrick Mahomes wins NFL MVP, Bob sends Alice $5.00 in 2027 draft auction dollars"
    draft_year: 2027
    paying_team: "Team Bob"
    receiving_team: "Team Alice"
    amount: 5.00
    status: "fulfilled"
notes: "Alice trades Patrick Mahomes, 2027 1st round pick, $5 in 2027, and $10 in 2028 to Bob for Justin Jefferson."
```

### 2.3 Consolidated `ledger.json` Schema

`ledger.json` contains active trades used by the server:

```json
{
  "version": 1,
  "last_compiled_at": "2026-11-07T18:00:00Z",
  "settle_through_year": 2025,
  "settled_trade_ids": ["trade-2025-001"],
  "active_trades": [
    {
      "id": "trade-2026-001",
      "date": "2026-11-07T16:00:00Z",
      "agreement_season": 2026,
      "source": { "jump_url": "..." },
      "parties": [ ... ],
      "conditions": [ ... ],
      "notes": "..."
    }
  ]
}
```

---

## 3. Financial Rules & Budget Arithmetic

### 3.1 Zero-Sum Invariant
For any trade record and any target draft year:
$$\sum_{\text{party} \in \text{parties}} \text{auction\_dollars}(\text{party}, \text{year}) = 0.00$$

Every dollar sent by one team is received by another. CI in the trade repo checks this invariant on all Pull Requests (`verify_ledger.py`).

### 3.2 Projected Auction Budget Formula
For a given team $T$ and draft year $Y$:
$$\text{Projected Budget}(T, Y) = \text{Starting Budget} + \text{Base Delta}(T, Y) + \text{Fulfilled Conditional Delta}(T, Y)$$

Where:
- **Starting Budget**: Configured per league (default `$200.00`).
- **Base Delta**: Net sum of all agreed unconditional auction dollars for draft year $Y$.
- **Fulfilled Conditional Delta**: Sum of conditional clauses targeting year $Y$ marked `status: "fulfilled"` (credited to receiving team, debited from paying team).
- **Pending Conditions**: Displayed as informational notes/badges without altering confirmed projections until resolved.

---

## 4. League Setup & Configuration

### 4.1 Step 1: Create the Trade Repository
1. Create a new GitHub repository (e.g. `bberk/whodat-trades`).
2. Copy files from `docs/trade-repo-template/` into the new repository.
3. Commit and push to `main`.
4. Create a fine-grained or classic GitHub Personal Access Token (PAT) with `repo` or `contents:read` permissions.

### 4.2 Step 2: Configure Whodat Server
1. Navigate to Whodat Server -> **Admin** -> **Trade Tracker Settings**.
2. Toggle **Enable Trade Tracking** to **ON**.
3. Set **Starting Auction Budget** (default `$200.00`).
4. Enter **Repository Owner** (e.g. `bberk`), **Repository Name** (e.g. `whodat-trades`), and **Branch** (`main`).
5. Enter the **GitHub Personal Access Token** (stored securely via AES-256-GCM encryption; never displayed in plaintext).
6. Set **Discord Channel ID** (ID of the `#trades` channel).
7. Configure **Team & Discord User Aliases** in the Alias Manager:
   - Map Discord handles (e.g. `@alice_ff`) and team names (e.g. `Team Alice`) to the canonical ESPN team name.
8. Click **Save Trade Tracker Settings**.

### 4.3 Step 3: Trigger Ingestion
- Click **Sync Trades from GitHub** to immediately fetch and calculate projected auction budgets.
- Once enabled, a **Trades** link automatically appears in the main navigation bar.

---

## 5. Automated Discord Agent Sync

The Discord sync agent can be run on a schedule or triggered manually via **Run Discord Trade Agent** from the admin page:

```
POST /api/v1/leagues/{league_id}/trades/discord-sync
```

1. The endpoint returns `202 Accepted` immediately, avoiding gateway timeouts.
2. The agent fetches messages since the last processed message ID from Discord `#trades`.
3. OpenCode / LLM extracts the structured trade parameters (parties, assets, draft years, conditions).
4. The agent checks open PRs on GitHub to avoid duplicate PRs.
5. A PR is opened with the trade YAML and updated `ledger.json` against `bberk/whodat-trades`.

---

## 6. Post-Draft Settlement Workflow

After each league's annual draft completes:
1. Navigate to `bberk/whodat-trades` -> **Actions** -> **Settle Post-Draft Trades**.
2. Click **Run workflow**, enter the completed draft year (e.g. `2026`), and submit.
3. The workflow moves trades that are fully executed through that draft year from `active_trades` to `settled_trade_ids` in `ledger.json`.
4. Review and merge the generated PR.
5. In Whodat Server, click **Sync Trades from GitHub** (or wait for the next sync). The settled trades are archived while all historical YAML records remain intact.
