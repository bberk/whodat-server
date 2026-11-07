# Implementation Plan: Discord Trade Tracker & Projected Auction Bucks

**Branch:** `discord_trade_tracker_plan`
**Status:** Updated Draft / Incorporating Multi-Draft, Ledger Truncation & OpenCode Server Ingestion
**Target Systems:** Discord, `bberk/whodat-trades` (GitHub), Production Server (OpenCode), `whodat-server` (Backend & Frontend)

---

## 1. Executive Summary & High-Level Architecture

Fantasy football dynasty and keeper leagues frequently trade future assets—most notably **auction draft dollars** and future draft picks—via Discord text chat in channels like `#trades`. Often, trades involve assets across **multiple future drafts** (for example: *Team A sends Mahomes + $5 in 2027 + $10 in 2028 for Justin Jefferson*). Fantasy platforms like ESPN do not natively support multi-year future auction budgets or trade logs.

This feature introduces an end-to-end, opt-in **Trade Tracker & Projected Auction Bucks Display** system:
1. **Discord Ingestion & AI Parsing via OpenCode on Production Server**: An automated job running on the production server uses an **OpenCode** installation (configured with multi-provider LLM access) to fetch `#trades` messages, extract structured multi-draft trades and conditional clauses, and submit them as Pull Requests to a dedicated Git repository (`bberk/whodat-trades`).
2. **Human-in-the-Loop Review**: League commissioners or managers review the PR diff on GitHub for accuracy and merge it into `main`.
3. **Versioned Trade Repo & Prunable Ledger**: Immutable historical trade files are kept permanently in `trades/YYYY/*.yaml`. A compiled `ledger.json` tracks active obligations and can be truncated after each season's draft to remove fully executed trades while preserving full history in Git and the server database.
4. **Whodat Server Sync**: The `whodat-server` backend fetches the trade ledger from GitHub using an encrypted token, calculates each team's net auction dollars adjustment for any target draft year, and computes projected auction budgets.
5. **Website Display**: The frontend displays a rich, interactive **Projected Auction Bucks Table** (with draft year switcher) alongside an audited **Trade History Feed**, with admin controls for budget baselines, manual sync triggers, and team alias mapping.

### End-to-End System Architecture

```mermaid
flowchart TD
    subgraph Discord["Discord Guild"]
        MSG["Trades posted in #trades"]
    end

    subgraph Prod_Server["Production Server (whodat Host)"]
        CRON["Scheduled Timer / Admin Trigger"]
        FETCH["Discord Fetcher (Watermark Cursors)"]
        OPENCODE["OpenCode Agent Runner"]
        PROVIDERS["Multi-Provider LLMs (Gemini / Anthropic / OpenAI)"]
        PR_BUILD["Format Multi-Year YAML & Open PR"]

        CRON --> FETCH --> OPENCODE
        PROVIDERS <--> OPENCODE
        OPENCODE --> PR_BUILD
    end

    subgraph Trade_Repo["GitHub Repo (bberk/whodat-trades)"]
        PR["Pull Request with Trade YAML"]
        REVIEW["Commissioner Review & Merge"]
        MAIN["main: trades/YYYY/*.yaml + ledger.json"]
        ARCHIVE["Post-Draft Ledger Truncation"]

        PR --> REVIEW --> MAIN
        MAIN --> ARCHIVE
    end

    subgraph Whodat_Server["Whodat Server (Backend)"]
        CONFIG["LeagueTradeConfig (Encrypted GitHub PAT)"]
        SYNC["TradeSyncService (Scheduled or Force Sync)"]
        DB[("Database: LeagueTradeConfig, Trade, BudgetDelta")]
        ENGINE["Domain: TradeBudgetEngine (Exact Decimal)"]
        API["FastAPI: /trade-config, /trades, /auction-budgets"]

        CONFIG --> SYNC
        SYNC --> DB
        DB --> ENGINE --> API
    end

    subgraph Frontend["React / TypeScript Frontend"]
        NAV["AppShell Nav (Trades Tab)"]
        ADMIN_UI["Admin: TradeTrackerSection"]
        AUCTION_TABLE["Projected Auction Bucks Table (2027, 2028)"]
        TRADE_FEED["Audited Trade History Cards"]

        API --> AUCTION_TABLE
        API --> TRADE_FEED
        ADMIN_UI --> API
    end

    MSG --> FETCH
    PR_BUILD --> PR
    MAIN -.-> SYNC
```

---

## 2. Subsystem 1: Discord AI Trade Extraction Engine via OpenCode

### 2.1 Execution Environment: Production Server with OpenCode

Rather than running on a local laptop (subject to sleep/disconnects) or purely inside GitHub Actions (subject to runner minute caps and secret management overhead), the extraction job runs directly on the **production server** using an **OpenCode** installation.

#### Architecture on the Production Server
The production server (described in `docs/DEPLOY_SERVER.md`) runs Docker Compose with Caddy, Postgres, and the backend. OpenCode can be integrated in one of two clean ways:
1. **Sidecar Container (`whodat-trade-agent`) in `docker-compose.yml` (Recommended)**:
   - Contains OpenCode CLI, Python 3.12, `git`, and `gh` (GitHub CLI).
   - Mounts a persistent volume for the cloned `whodat-trades` working directory and `.watermark.json`.
   - Configured via environment variables in `deploy/server/.env`.
2. **Host Systemd Service / Timer**:
   - Installed on the host OS, triggered every 6–12 hours (e.g., 04:00 and 16:00 UTC) via `systemd.timer`.

#### Multi-Provider LLM Configuration
OpenCode is configured to access multiple AI providers with automatic fallbacks:
```json
{
  "default_provider": "gemini",
  "providers": {
    "gemini": {
      "model": "gemini-2.0-flash",
      "api_key_env": "GEMINI_API_KEY",
      "temperature": 0.1
    },
    "anthropic": {
      "model": "claude-3-5-sonnet-latest",
      "api_key_env": "ANTHROPIC_API_KEY",
      "temperature": 0.1
    },
    "openai": {
      "model": "gpt-4o",
      "api_key_env": "OPENAI_API_KEY",
      "temperature": 0.1
    }
  }
}
```
If the primary provider hits a quota limit or downtime, OpenCode seamlessly falls back to the secondary provider.

### 2.2 Discord Ingestion & Watermarking

1. **Discord REST Ingestion**:
   - A lightweight helper fetches messages from `#trades` using a Discord Bot token with `Read Message History` permission.
   - Paginates forward starting from `last_message_id` stored in `.watermark.json`:
     ```json
     {
       "channel_id": "123456789012345678",
       "last_message_id": "130458923485723490",
       "last_sync_timestamp": "2026-11-07T18:00:00Z"
     }
     ```
2. **Context Window Assembly**:
   - Discord trades frequently span multiple messages (e.g., Manager A states terms; Manager B replies *"confirmed"* or reacts with a thumbs-up emoji).
   - The ingestion script bundles root trade messages with their replies/reactions before feeding them to OpenCode.

### 2.3 Multi-Draft Extraction Schema

Trades frequently divide auction money across several upcoming draft years.
*Example:* **"Alice trades Mahomes + $5 in 2027 and $10 in 2028 to Bob for Justin Jefferson."**

The prompt instructs OpenCode to extract trades conforming to the following structured output:

```json
{
  "trades_found": [
    {
      "source_message_id": "130458923485723490",
      "source_jump_url": "https://discord.com/channels/.../...",
      "timestamp": "2026-11-07T16:30:00Z",
      "confirmed": true,
      "agreement_season": 2026,
      "parties": [
        {
          "team_name": "Team Alice",
          "discord_author": "alice_ff",
          "players_sent": ["Patrick Mahomes"],
          "players_received": ["Justin Jefferson"],
          "auction_dollars": [
            { "draft_year": 2027, "amount": -5.00 },
            { "draft_year": 2028, "amount": -10.00 }
          ]
        },
        {
          "team_name": "Team Bob",
          "discord_author": "bob_commish",
          "players_sent": ["Justin Jefferson"],
          "players_received": ["Patrick Mahomes"],
          "auction_dollars": [
            { "draft_year": 2027, "amount": 5.00 },
            { "draft_year": 2028, "amount": 10.00 }
          ]
        }
      ],
      "conditions": [
        {
          "id": "cond-1",
          "description": "If Mahomes wins MVP in 2026, Bob pays Alice an extra $5 in 2028",
          "draft_year": 2028,
          "potential_amount": 5.00,
          "paying_team": "Team Bob",
          "receiving_team": "Team Alice",
          "status": "pending"
        }
      ],
      "raw_text": "Alice: Patrick Mahomes + $5 2027 + $10 2028 for Justin Jefferson\nBob: Deal"
    }
  ]
}
```

### 2.4 PR Automation Workflow

When valid trades are parsed:
1. OpenCode creates a git branch in the local clone of `bberk/whodat-trades`: `trade/sync-YYYY-MM-DD-HHMM`.
2. Writes the trade YAML file to `trades/<agreement_season>/<date>_<slug>.yaml`.
3. Updates `.watermark.json`.
4. Pushes the branch to GitHub using the server's configured `GH_TOKEN`.
5. Opens a Pull Request with a clear Markdown description, asset exchange tables broken down by draft year, and raw Discord quote.

---

## 3. Subsystem 2: Trade Repository Architecture (`bberk/whodat-trades`)

### 3.1 Adopted Structure: Hybrid Option 3 with Prunable Ledger

```
trades/
  2025/
    2025-10-12_cmc_picks.yaml
  2026/
    2026-11-07_mahomes_jefferson.yaml
    2026-11-20_henry_cash.yaml
ledger.json          <-- Active/unsettled trades + draft balances
.watermark.json      <-- Discord ingestion cursor
```

- **`trades/` directory (Immutable History)**: Keeps every trade YAML permanently. Trade files are **never deleted**. This serves as the unalterable audit log of all transactions in league history.
- **`ledger.json` (Active Working Ledger)**: The consolidated, lightweight index consumed by `whodat-server`. Only contains trades that have **active / unsettled obligations** for current or upcoming drafts.
- **Merge Conflict Freedom**: New trades are submitted as independent files in `trades/`, so multiple PRs never conflict with one another.

### 3.2 Canonical Trade Schema (`trades/YYYY/YYYY-MM-DD_<slug>.yaml`)

```yaml
version: 1
id: "2026-11-07-alice-bob"
date: "2026-11-07T16:30:00Z"
agreement_season: 2026
source:
  platform: "discord"
  channel: "trades"
  message_id: "130458923485723490"
  jump_url: "https://discord.com/channels/123/456/130458923485723490"
parties:
  - team_name: "Team Alice"
    discord_user: "alice_ff"
    players_sent:
      - name: "Patrick Mahomes"
        position: "QB"
        nfl_team: "KC"
    players_received:
      - name: "Justin Jefferson"
        position: "WR"
        nfl_team: "MIN"
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
        nfl_team: "MIN"
    players_received:
      - name: "Patrick Mahomes"
        position: "QB"
        nfl_team: "KC"
    auction_dollars:
      - draft_year: 2027
        amount: 5.00
      - draft_year: 2028
        amount: 10.00
conditions:
  - id: "cond-1"
    description: "If Patrick Mahomes wins MVP, Team Bob pays extra $5 in 2028"
    draft_year: 2028
    paying_team: "Team Bob"
    receiving_team: "Team Alice"
    amount: 5.00
    status: "pending" # pending | fulfilled | void
notes: |
  Agreed in #trades on Nov 7, 2026.
```

### 3.3 Zero-Sum Constraint Per Draft Year
CI validates that for **every distinct `draft_year`** in a trade:
$$\forall Y \in \text{DraftYears}, \quad \sum_{p \in \text{parties}} \text{auction\_dollars}(p, Y) = 0$$
Auction money cannot be created or destroyed in any draft year.

### 3.4 Ledger Truncation & Post-Draft Settling

After each season's fantasy draft completes (typically late August):
1. **Fully Executed Criteria**:
   A trade is considered **fully executed** when:
   - All `draft_year` values in its `auction_dollars` entries are $\le \text{settled\_draft\_year}$.
   - All conditions attached to the trade have been resolved (`status: fulfilled` or `status: void`).
2. **Partial Multi-Year Trades**:
   If a trade has \$5 for 2026 and \$10 for 2028, after the 2026 draft finishes:
   - The 2026 obligation is settled and no longer impacts active projections.
   - The trade **remains** in `ledger.json` because its 2028 obligation is still pending!
3. **Truncation Automation**:
   - A script in the repo: `python scripts/compile_ledger.py --settle-through 2026`.
   - Generates `ledger.json` containing only active future trades and updates metadata:
     ```json
     {
       "settled_through_draft_year": 2026,
       "active_draft_years": [2027, 2028],
       "compiled_at": "2026-09-01T00:00:00Z",
       "active_trades": [ ... ],
       "projected_balances": {
         "2027": { "Team Alice": -5.00, "Team Bob": 5.00 },
         "2028": { "Team Alice": -10.00, "Team Bob": 10.00 }
       }
     }
     ```
   - All historical YAML files in `trades/2026/` remain untouched.
   - The `whodat-server` retains all historical trades in its database for the audit log, but only uses active draft years for upcoming budget calculations.

---

## 4. Subsystem 3: Whodat Server Integration Architecture

### 4.1 Database Models & Alembic Migration (`0012_trade_tracker.py`)

To handle multi-draft auction dollars cleanly, adjustments are stored in a normalized child table `league_trade_budget_delta`:

```python
"""Add league trade tracking and multi-draft auction budget tables."""

# Tables:
# 1. league_trade_config
#    - league_id (FK league.id, UNIQUE)
#    - enabled (Boolean, default False)
#    - repo_owner (Text, e.g. "bberk")
#    - repo_name (Text, e.g. "whodat-trades")
#    - branch (Text, default "main")
#    - github_token_encrypted (Text, nullable)
#    - base_auction_budget (Numeric(10, 2), default 200.00)
#    - team_aliases (JSON, default {})
#    - last_synced_at (DateTime(timezone=True), nullable)
#    - last_sync_commit (Text, nullable)
#    - last_sync_status (Text, default "idle")
#    - last_sync_error (Text, nullable)

# 2. league_trade
#    - id (Integer, PK)
#    - league_id (FK league.id)
#    - external_trade_id (Text) # e.g. "2026-11-07-alice-bob"
#    - date (DateTime(timezone=True))
#    - agreement_season (Integer) # e.g. 2026
#    - is_settled (Boolean, default False)
#    - discord_url (Text, nullable)
#    - summary (Text)
#    - raw_yaml (Text)
#    - conditions (JSON, default [])
#    - uq_league_trade (league_id, external_trade_id)

# 3. league_trade_party
#    - id (Integer, PK)
#    - trade_id (FK league_trade.id, ON DELETE CASCADE)
#    - owner_id (FK owner.id, nullable)
#    - team_name_raw (Text)
#    - players_sent (JSON)
#    - players_received (JSON)

# 4. league_trade_budget_delta
#    - id (Integer, PK)
#    - party_id (FK league_trade_party.id, ON DELETE CASCADE)
#    - league_id (FK league.id)
#    - draft_year (Integer) # e.g. 2027 or 2028
#    - amount (Numeric(10, 2)) # signed delta (e.g. -5.00, +10.00)
#    - ix_budget_delta (league_id, draft_year)
```

### 4.2 GitHub Sync Service (`TradeSyncService`)

Located at `backend/src/app/services/trade_sync_service.py`:
1. **GitHub Ingestion**: Reads `ledger.json` from the configured private repository using the AES-256-GCM decrypted GitHub token.
2. **Alias Resolution**:
   - Matches raw trade names (`"Team Alice"`, `"alice_ff"`) to canonical league `Owner` records.
   - Falls back to `league_trade_config.team_aliases` mapping.
   - Flags unmapped names for admin review.
3. **Database Upsert**:
   - Upserts trades and budget deltas idempotently based on `(league_id, external_trade_id)`.
   - If a trade was truncated from `ledger.json` because it was settled, `whodat-server` marks existing records as `is_settled = True` rather than deleting them, preserving league history.
4. **Admin Force Sync**:
   - Rate-limited to max 1 sync per 30 seconds per league to prevent GitHub API throttling.

### 4.3 Domain Calculation Engine (`app.domain.trade_budget`)

Pure standard-library module with 100% test coverage using exact `Decimal` arithmetic:
- **Starting Budget**: `base_auction_budget` (e.g., \$200.00).
- **For a selected `target_draft_year` (e.g., 2027)**:
  $$\text{Net Delta}_i(Y) = \sum_{t \in \text{Trades}} \sum_{d \in t.\text{deltas}(i, Y)} d.\text{amount}$$
  $$\text{Projected Budget}_i(Y) = \text{Starting Budget} + \text{Net Delta}_i(Y)$$
  $$\text{Pending Conditional Delta}_i(Y) = \sum_{c \in \text{PendingConditions}(i, Y)} c.\text{amount}$$

### 4.4 API Endpoints

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/leagues/{league_id}/trade-config` | Admin | Trade tracker settings, sync status, and team mappings. |
| `PUT` | `/leagues/{league_id}/trade-config` | Admin | Update repo, token, base budget, and aliases. |
| `POST` | `/leagues/{league_id}/trades/sync` | Admin | Trigger immediate GitHub sync. |
| `GET` | `/leagues/{league_id}/trades` | Member | List trade history log with filters (team, draft year). |
| `GET` | `/leagues/{league_id}/auction-budgets?draft_year={year}` | Member | Table of projected auction budgets for the specified draft year. |

---

## 5. Subsystem 4: Frontend UI & User Experience

### 5.1 AppShell Navigation
- When `selectedLeague.has_trades_enabled === true`, the navigation header displays **Trades**:
  `Standings | History | Trades | Owner | Admin`
- Route: `/leagues/:leagueId/trades`.

### 5.2 Admin Settings Panel (`TradeTrackerSection.tsx`)
In `AdminPage.tsx`:
- Opt-in feature toggle.
- GitHub repo coordinates (`bberk/whodat-trades`, branch `main`).
- GitHub PAT (write-only, masked when saved).
- Base starting budget input (default `$200.00`).
- **Team Alias Mapping Tool**: Table showing unmapped names extracted from recent trades with a dropdown selector to assign them to official League Owners.
- **Sync Control**: "Sync from GitHub" button with status badge ("Last synced 5 mins ago; commit `8c2f1d`").

### 5.3 Trades & Auction Page (`TradesPage.tsx`)

#### View 1: Projected Auction Bucks
- **Draft Year Picker**: Dropdown / toggle pills (e.g. `2027 Draft ($)`, `2028 Draft ($)`).
- **Responsive Table**:
  - **Team / Owner** (sticky on mobile).
  - **Starting Budget** (\$200.00).
  - **Net Trade Delta** (e.g., `-$5.00` in red or `+$15.00` in green).
  - **Projected Budget** (e.g., **`$195.00`** in bold).
  - **Pending Conditions** (badge with popover: e.g. `+$5 pending MVP`).
  - **Active Trades Count**.
- Clicking a team row opens a drawer/modal displaying every trade contributing to that team's delta for the selected draft year.

#### View 2: Trade History Feed
- Searchable by player and filterable by team or draft year.
- Each trade card displays:
  - Date and Discord permalink button.
  - Multi-draft asset breakdown (players + \$ per draft year).
  - Explicit badges for multi-year cash:
    - `💸 2027: $5.00 from Alice to Bob`
    - `💸 2028: $10.00 from Alice to Bob`
  - Conditional clauses with status badge (`Pending`, `Fulfilled`, `Void`).
  - Expandable Discord message quote.

---

## 6. Implementation Roadmap for Workers

```mermaid
flowchart LR
    M1["Milestone 1:<br/>Trade Repo Schema & CI"] --> M2["Milestone 2:<br/>OpenCode Ingestion & PR"]
    M1 --> M3["Milestone 3:<br/>Backend DB & Crypto"]
    M3 --> M4["Milestone 4:<br/>Backend Sync & Multi-Year Budget API"]
    M4 --> M5["Milestone 5:<br/>Frontend Admin UI"]
    M4 --> M6["Milestone 6:<br/>Frontend Trades & Bucks Display"]
    M5 --> M7["Milestone 7:<br/>E2E & Production Verification"]
    M6 --> M7
```

### Milestone 1: Trade Repository & Truncation Tooling (`bberk/whodat-trades`)
- [ ] Create repository `bberk/whodat-trades`.
- [ ] Implement multi-draft YAML trade schema.
- [ ] Implement GitHub Actions CI:
  - Validates zero-sum balance rule for **each individual draft year**.
  - Auto-compiles `ledger.json` on merge to `main`.
- [ ] Add `scripts/compile_ledger.py` with `--settle-through <year>` for post-draft pruning.

### Milestone 2: Production Server OpenCode Ingestion Service
- [ ] Add `whodat-trade-agent` container / runner definition with OpenCode CLI.
- [ ] Configure multi-provider LLM settings in `deploy/server/.env` (Gemini primary, Anthropic fallback).
- [ ] Implement Discord message fetcher with `.watermark.json` cursor.
- [ ] Implement OpenCode trade extraction prompt with multi-draft JSON schema.
- [ ] Implement git commit and PR opening automation.

### Milestone 3: Whodat Backend Models, Migrations & Encryption
- [ ] Alembic migration `0012_trade_tracker.py` for `league_trade_config`, `league_trade`, `league_trade_party`, `league_trade_budget_delta`.
- [ ] SQLAlchemy models in `backend/src/app/db/models.py`.
- [ ] AES-256-GCM encryption verification for GitHub PAT.
- [ ] Database repositories and queries for draft-year-filtered trade data.

### Milestone 4: Backend Domain Engine, Sync Service & API Endpoints
- [ ] Implement pure domain logic in `backend/src/app/domain/trade_budget.py` (exact `Decimal` math, 100% coverage).
- [ ] Implement `TradeSyncService` in `backend/src/app/services/trade_sync_service.py` with alias resolution and idempotent upsert.
- [ ] Implement schemas and endpoints in `routes_trades.py` (`/trade-config`, `/trades`, `/auction-budgets`).
- [ ] Update `docs/openapi.json`.

### Milestone 5: Frontend Admin Settings & Dynamic Navigation
- [ ] Regenerate frontend API types with `pnpm gen:api`.
- [ ] Add `TradeTrackerSection.tsx` to `AdminPage.tsx`.
- [ ] Add conditional `Trades` navigation tab in `AppShell.tsx`.
- [ ] Unit tests for admin trade tracker configuration and alias mapper.

### Milestone 6: Frontend Trades & Projected Auction Bucks Page
- [ ] Implement `frontend/src/pages/TradesPage.tsx`.
- [ ] Implement `ProjectedAuctionTable.tsx` with draft year switcher and mobile sticky column.
- [ ] Implement `TradeLogFeed.tsx` with multi-year cash badges, player search, and filters.
- [ ] Implement loading, empty, and error states.

### Milestone 7: End-to-End Verification & Production Runbook
- [ ] Write integration tests for multi-draft trades, settling, and sync rate limits.
- [ ] Verify pre-commit hooks (`ruff`, `mypy`, `vitest`).
- [ ] Document production server OpenCode setup in `docs/DEPLOY_SERVER.md`.
