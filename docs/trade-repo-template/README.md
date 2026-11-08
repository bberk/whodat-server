# Fantasy Football Trade Repository Template

This repository acts as the authoritative version-controlled log of trades for fantasy football
leagues configured with Whodat Server's Trade Tracker.

---

## 1. Repository Structure

```
├── .github/workflows/
│   ├── verify-ledger.yml       # CI zero-sum balance and schema verification
│   └── settle-draft.yml        # Manual workflow to archive settled trades post-draft
├── scripts/
│   ├── verify_ledger.py        # Python zero-sum validator
│   └── settle_draft.py         # Python draft settlement script
├── trades/
│   └── <season>/               # Directory per trade agreement season (e.g. 2026/)
│       └── trade-*.yaml        # Individual trade YAML records
└── ledger.json                 # Consolidated active trades and settled trade IDs
```

---

## 2. How It Works

1. **Trade Announcement & Ingestion**:
   - A trade is agreed upon and posted in the league's Discord `#trades` channel.
   - The Whodat Server trade agent runs (scheduled or triggered from Whodat Admin), fetches recent
     announcements, extracts structured trade parameters using AI, and opens a Pull Request against
     this repository containing a new `trade-*.yaml` and updated `ledger.json`.
2. **Review & Approval**:
   - League commissioners and members review the Pull Request for accuracy.
   - GitHub Actions (`verify-ledger.yml`) validates that all auction dollar deltas are zero-sum
     across each target draft year and that draft picks match.
   - Once approved, the PR is merged into `main`.
3. **Whodat Server Ingestion**:
   - Whodat Server syncs `ledger.json` from this repository via GitHub API and calculates exact
     projected auction budgets per draft year using deterministic Decimal arithmetic.
4. **Post-Draft Archiving**:
   - After each annual draft, trigger the `Settle Post-Draft Trades` workflow (`settle-draft.yml`)
     with the completed draft year.
   - The workflow moves fully executed trades from `active_trades` to `settled_trade_ids` in
     `ledger.json`, opening a PR for quick approval.
   - Historical YAML files in `trades/` remain permanently preserved for record-keeping.

---

## 3. How to Set Up the Trade Repository

### 3.1 Create the Repository
1. In GitHub, create a new repository (e.g. `your-org/fantasy-trades`). It may be private or public.
2. Copy all files and directories from `docs/trade-repo-template/` into your new repository.
3. Ensure `ledger.json` is initialized with the initial envelope:
   ```json
   {
     "version": 1,
     "last_compiled_at": null,
     "settle_through_year": null,
     "settled_trade_ids": [],
     "active_trades": []
   }
   ```
4. Commit and push these files to the `main` branch.

### 3.2 Branch Protection Rules (Recommended)
To prevent accidental pushes that violate financial zero-sum balance:
1. Navigate to **Settings** -> **Branches** in your GitHub repository.
2. Add a branch protection rule for `main`.
3. Check **Require a pull request before merging**.
4. Check **Require status checks to pass before merging** and select `Verify Trade Ledger`.

---

## 4. GitHub Personal Access Token (PAT) Configuration

Whodat Server reads `ledger.json` via the GitHub REST API. If the trade repository is private (or
to avoid GitHub API rate limits), configure a GitHub Personal Access Token in Whodat Server:

### 4.1 Token Creation
1. Go to GitHub -> **Settings** -> **Developer Settings** -> **Personal Access Tokens**.
2. **Fine-grained Personal Access Token** (Recommended):
   - **Repository access**: Select **Only select repositories** and pick your trade repository.
   - **Permissions**:
     - `Contents`: **Read-only** (if only syncing trades into Whodat Server) or **Read and Write**
       (if the server's OpenCode trade agent opens automated PRs).
     - `Pull requests`: **Read and Write** (required if using automated PR opening).
     - `Metadata`: **Read-only** (default).
3. **Classic Token** (Alternative):
   - Select scope `repo` for full private repository access.

### 4.2 Adding the Token in Whodat Server
1. Navigate to Whodat Server -> **Admin** -> **Trade tracker & auction budget**.
2. Switch the Trade Tracker toggle to **Enabled**.
3. In the **GitHub Personal Access Token (PAT)** field, paste your generated token.
4. Click **Save Trade Settings**.
5. The token is encrypted using AES-256-GCM prior to storage and is never exposed in plaintext
   or returned in API responses.

---

## 5. Discord Application & Bot Setup

To ingest trade announcements from a Discord channel—especially in a **private Discord server**—
you must create a Discord Application/Bot and grant it access to the channel:

### 5.1 Step 1: Create the Discord Application and Bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and enter an application name (e.g. `Whodat Trade Bot`).
3. In the left sidebar, navigate to **Bot**.
4. Under **Token**, click **Reset Token** (and complete 2FA if prompted).
5. Copy the generated Bot Token immediately. You will provide this to Whodat Server.
6. Under **Privileged Gateway Intents**, enable **Message Content Intent** (required so the bot
   can read message text posted in the `#trades` channel).

### 5.2 Step 2: Invite the Bot to Your Discord Server
1. In the left sidebar, navigate to **OAuth2** -> **URL Generator**.
2. Under **Scopes**, select `bot`.
3. Under **Bot Permissions**, select:
   - `View Channels` (Read messages/view channel)
   - `Read Message History`
   - `Send Messages` (optional, for notifications or reactions)
4. Copy the generated **Invite URL** at the bottom of the page.
5. Paste the URL into your browser, select your fantasy football Discord server, and click
   **Authorize**.

### 5.3 Step 3: Grant Access in Private Channels
If your Discord server or `#trades` channel is private:
1. Open Discord, right-click your `#trades` channel, and select **Edit Channel**.
2. Go to **Permissions** -> **Advanced Permissions**.
3. Under **Roles/Members**, add your bot (`Whodat Trade Bot`).
4. Ensure the following permissions are green (allowed):
   - **View Channel**
   - **Read Message History**

### 5.4 Step 4: Obtain the Channel ID
1. In Discord, go to **User Settings** -> **Advanced** -> toggle on **Developer Mode**.
2. Right-click the `#trades` channel in your server channel list.
3. Click **Copy Channel ID** (an 18–19 digit numeric ID).

### 5.5 Step 5: Configure in Whodat Server
1. Navigate to Whodat Server -> **Admin** -> **Trade tracker & auction budget**.
2. In **Discord #trades Channel ID**, enter the channel ID copied in Step 4.
3. In **Discord Bot Token**, paste the bot token copied in Step 1.
4. Alternatively, for global server-wide setup, administrators can set the `DISCORD_BOT_TOKEN`
   environment variable on the Whodat Server backend.
5. Click **Save Trade Settings**.
6. Click **Sync Discord Trades** to trigger immediate background ingestion.
