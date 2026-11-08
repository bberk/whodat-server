# Fantasy Football Trade Repository Template

This repository acts as the authoritative version-controlled log of trades for fantasy football leagues configured with Whodat Server's Trade Tracker.

## Repository Structure

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

## How It Works

1. **Trade Announcement & AI Ingestion**:
   - A trade is agreed upon and announced in the league's Discord `#trades` channel.
   - The Whodat Server trade agent runs (scheduled or manually triggered from Whodat Admin), reads new messages, parses trade assets using AI, and opens a Pull Request against this repository containing a new `trade-*.yaml` and updated `ledger.json`.
2. **Review & Approval**:
   - League commissioners/members review the Pull Request for accuracy.
   - GitHub Actions (`verify-ledger.yml`) validates that all auction dollar deltas are zero-sum across each draft year and that draft picks match.
   - Once approved, the PR is merged into `main`.
3. **Whodat Server Ingestion**:
   - Whodat Server syncs `ledger.json` from this repository via GitHub API and calculates exact projected auction budgets per draft year.
4. **Post-Draft Archiving**:
   - After each annual draft, trigger the `Settle Post-Draft Trades` workflow (`settle-draft.yml`) with the completed draft year.
   - The workflow moves fully executed trades from `active_trades` to `settled_trade_ids` in `ledger.json`, opening a PR for quick approval.
   - Historical YAML files in `trades/` remain permanently preserved for record-keeping.
