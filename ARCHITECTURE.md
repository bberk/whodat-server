# ARCHITECTURE: Victory Points Fantasy Football Standings

> Status: DRAFT v0.1. Assumes the proposed stack in SPEC.md section 7. If the stack changes, keep the boundaries and contracts below and swap the names.

## 1. System overview

```
 ┌────────────┐   normalized DTOs   ┌─────────────┐   rows   ┌──────────┐
 │ Provider   │ ──────────────────▶ │ Sync service│ ───────▶ │          │
 │ (ESPN,     │                     └──────┬──────┘          │ Database │
 │  Fake, …)  │                            │ calls           │ (SQLite/ │
 └────────────┘                     ┌──────▼──────┐          │ Postgres)│
                                    │ VP engine   │          │          │
                                    │ (pure)      │          └────┬─────┘
                                    └─────────────┘               │
                          ┌───────────────────────────────────────▼──┐
                          │ Standings service ─▶ FastAPI JSON API    │
                          └──────────────────────────┬───────────────┘
                                                     │ HTTPS + OpenAPI
                                              ┌──────▼───────┐
                                              │ React SPA    │
                                              └──────────────┘
```

Key principle: **dependencies point inward**. The VP engine knows nothing about ESPN, the database, or HTTP. The sync service knows providers only through an interface. The API knows nothing about ESPN.

## 2. Repository layout

```
/
├── SPEC.md  ACCEPTANCE.md  ARCHITECTURE.md  AGENTS.md  README.md
├── .pre-commit-config.yaml      # commit and push hooks (section 13)
├── .github/
│   ├── workflows/ci.yml         # CI + coverage comment
│   └── pull_request_template.md
├── .opencode/agents/reviewer.md # independent reviewer agent definition
├── .opencode/pull-requests.md   # how the author agent opens and fills in a PR
├── scripts/                     # ship.sh, cleanup.sh, review.sh, merge.sh, setup-github.sh,
│                                #   dev-postgres.sh, coverage_report.py
├── docs/
│   ├── GITHUB_SETUP.md          # one-time owner checklist
│   ├── OPEN_QUESTIONS.md        # agents append questions here
│   └── fixtures/                # recorded provider payloads, golden JSON
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                 # migrations
│   ├── src/app/
│   │   ├── domain/              # engine + pure types (no I/O)
│   │   │   ├── vp_engine.py
│   │   │   ├── standings.py     # ranking + tiebreakers (pure)
│   │   │   └── types.py
│   │   ├── providers/
│   │   │   ├── base.py          # LeagueProvider protocol + DTOs
│   │   │   ├── registry.py
│   │   │   ├── fake.py
│   │   │   └── espn/            # ONLY place that imports espn_api
│   │   ├── db/                  # SQLAlchemy models, session, repositories
│   │   ├── services/            # sync_service.py, standings_service.py, auth_service.py
│   │   ├── api/                 # FastAPI routers, schemas, dependencies
│   │   ├── cli.py               # `sync`, `recompute`, `create-user` commands
│   │   └── config.py            # env-driven settings
│   └── tests/
├── frontend/
│   ├── package.json
│   └── src/
│       ├── api/                 # generated types + thin client
│       ├── components/
│       ├── pages/
│       └── lib/
└── docker-compose.yml
```

## 3. Module responsibilities and boundaries

| Module | Responsibility | May import | Must NOT import |
|---|---|---|---|
| `domain/` | VP computation, standings ranking, tie splitting | stdlib only (`decimal`, `fractions`, `dataclasses`) | db, api, providers, any I/O |
| `providers/base.py` | `LeagueProvider` protocol and normalized DTOs | stdlib, pydantic | db, api, domain internals |
| `providers/espn/` | ESPN → DTO translation | `espn_api`, `providers.base` | db, api, domain |
| `providers/fake.py` | In-memory provider for tests/dev | `providers.base` | everything else |
| `db/` | Models, session handling, repositories | sqlalchemy, `domain.types` | api, providers |
| `services/` | Orchestrates the other layers | domain, db, providers.base | `espn_api`, fastapi |
| `api/` | HTTP routes, request/response schemas, auth dependencies | services, fastapi | `espn_api`, db models directly (go through services) |
| `frontend/` | UI | generated API types | nothing in `backend/` |

These boundaries are enforced by an automated import test (AC-VP-14, AC-PR-03).

## 4. Data model

All tables have `id` (integer PK) and `created_at`/`updated_at`. Natural keys are enforced with unique constraints so that sync can upsert safely.

### `league`
`provider` (text, e.g. `espn`), `external_id` (text), `name`, `metadata` (JSON: scoring settings, number of teams, regular season length, etc.), `provider_config_ref` (text; a pointer to credentials in config, **not** the credentials themselves).
Unique: (`provider`, `external_id`).

### `owner`
`league_id` → league, `external_id` (provider's owner/member ID), `display_name`.
Unique: (`league_id`, `external_id`).

### `team`
`league_id`, `season` (int), `external_id`, `name`, `division` (text, nullable), `owner_id` → owner (nullable).
Unique: (`league_id`, `season`, `external_id`).

### `matchup`
`league_id`, `season`, `week`, `home_team_id` → team, `away_team_id` → team (nullable for byes), `is_playoff` (bool), `is_complete` (bool).
Unique: (`league_id`, `season`, `week`, `home_team_id`).

### `score`
`team_id` → team, `league_id`, `season`, `week`, `points` (NUMERIC(8,2)), `victory_points` (NUMERIC(10,6)), `vp_h2h`, `vp_top_half`, `vp_high`, `vp_low` (each NUMERIC(10,6)).
Unique: (`team_id`, `season`, `week`).

### `app_user`
`email` (unique, stored lowercase), `password_hash`, `owner_id` → owner (nullable until linked), `created_at`.

### Numeric rules

- `points` are exact decimals with 2 decimal places (ESPN reports floats; round to 2 dp on ingest via string conversion, e.g. `Decimal(str(x)).quantize(Decimal("0.01"))`).
- The engine computes VP with `fractions.Fraction`. When persisting, store the NUMERIC value; when ranking, **sum from the exact components in application code** (do not rank using rounded stored values) so that 1/3 + 1/3 + 1/3 compares equal to 1.
- Never use `float` for scores or VP anywhere in `domain/`, `db/`, or `services/`.

## 5. Provider interface

```python
class LeagueProvider(Protocol):
    provider_id: str  # "espn", "fake", ...

    def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO: ...
    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]: ...
    def fetch_teams(self, league_ref: LeagueRef, season: int) -> list[TeamDTO]: ...
    def fetch_matchups(self, league_ref: LeagueRef, season: int, week: int) -> list[MatchupDTO]: ...
    # MatchupDTO carries both teams' points; scores are derived from it.
    def current_week(self, league_ref: LeagueRef, season: int) -> WeekStatus: ...
```

DTO rules:

- DTOs are provider-agnostic dataclasses/Pydantic models with `external_id` strings and `Decimal` points.
- A `MatchupDTO` has `week`, `home` and `away` entries (`team_external_id`, `points`), `away` is optional for byes, plus `is_playoff` and `is_complete`.
- The ESPN adapter translates ESPN payloads and quirks into these DTOs and nothing else. All ESPN quirks (cookie auth, division names, bye representation, playoff detection) are contained in `providers/espn/`.
- Providers are looked up by `provider_id` in `providers/registry.py`.

## 6. Sync flow

`sync_service.sync_league(league, season, weeks=None)`:

1. Fetch league, owners, teams from the provider; upsert.
2. Determine weeks to sync (default: all weeks up to and including the current completed week).
3. For each week: fetch matchups; upsert matchups; upsert scores' `points`.
4. For each week whose matchup/score data changed (or is newly completed): load that week's scores and matchups, run the VP engine, and write `victory_points` and components for all teams in that week, in a single transaction.
5. Weeks that are playoffs or incomplete are stored but receive no VP (VP columns remain 0 and are excluded from standings).

Sync is idempotent (AC-DB-02): upserts compare values and only write on change.

CLI: `python -m app.cli sync --league <id> --season <year> [--weeks 1-5]` and `python -m app.cli recompute --league <id> --season <year>` (recompute VP only, no provider calls).

## 7. VP engine contract

```python
# domain/types.py
@dataclass(frozen=True)
class TeamWeek:
    team_id: int
    points: Decimal
    opponent_id: int | None   # None = bye

@dataclass(frozen=True)
class WeekVP:
    team_id: int
    h2h: Fraction
    top_half: Fraction
    high: Fraction
    low: Fraction
    @property
    def total(self) -> Fraction: ...

def compute_week_vp(teams: Sequence[TeamWeek]) -> dict[int, WeekVP]: ...
```

Algorithm notes (see SPEC 3 and ACCEPTANCE 1.1 for authoritative rules and examples):

- Group teams by exact `points`. Process tie groups in rank order.
- Top-half pool: for a tie group occupying ranks `r..r+k-1` (1-indexed), slots inside the cutoff = `max(0, min(r+k-1, floor(N/2)) - r + 1)`; each member gets `slots / k`.
- High: the first group splits +1; low: the last group splits -1.
- H2H: compare points of each matched pair; tie → 0.5 each.

```python
# domain/standings.py
def rank_teams(rows: Sequence[SeasonRow]) -> list[RankedRow]: ...
# sort key: (-vp, -h2h_wins, -points_for); equal keys share a rank number.
```

## 8. API contract

All endpoints are under `/api/v1`, JSON, cookie-session or bearer-token auth (backend implementer's choice; httpOnly cookie preferred). FastAPI publishes OpenAPI; the backend commits an exported `docs/openapi.json` on every API change, and the frontend generates TypeScript types from it (e.g. `openapi-typescript`).

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /auth/signup` | none | Create account (email, password) |
| `POST /auth/login` | none | Log in |
| `POST /auth/logout` | user | Log out |
| `GET /me` | user | Current user, linked owner and league |
| `GET /leagues/{league_id}/owners` | user (during linking) | Owners available to claim (see SPEC **[OPEN]** Q3) |
| `POST /me/link-owner` | user | Link the current user to an owner |
| `GET /leagues/{league_id}/seasons` | member | Seasons with data |
| `GET /leagues/{league_id}/seasons/{season}/standings` | member | Overall standings + divisions (shape below) |
| `GET /leagues/{league_id}/seasons/{season}/vp-history` | member | Weekly and cumulative VP per team (for the chart) |

"member" = authenticated user whose owner belongs to the league.

### Standings response (shape)

```json
{
  "league_id": 1, "season": 2026, "completed_weeks": 6,
  "overall": [
    {
      "rank": 1, "team_id": 7, "team_name": "…", "owner_name": "…", "division": "East",
      "victory_points": "31.5", "wins": 4, "losses": 2, "ties": 0, "points_for": "812.34",
      "weekly_vp": ["3", "2.5", "…"]
    }
  ],
  "divisions": [
    { "name": "East", "standings": [ /* same row shape, rank within division */ ] }
  ]
}
```

VP and points are serialized as **strings** (decimal), so the frontend never relies on binary floats for display. VP values display with up to 2 decimals (e.g. `0.33`), trimming trailing zeros.

### VP history response (shape)

```json
{
  "weeks": [1, 2, 3],
  "teams": [
    { "team_id": 7, "team_name": "…", "weekly": ["3", "2.5", "-1"], "cumulative": ["3", "5.5", "4.5"] }
  ]
}
```

## 9. Frontend architecture

- **Routing**: `/login`, `/signup`, `/link-owner`, `/` (standings for the user's league and current season).
- **State**: server state via TanStack Query; local UI state (selected team, hidden chart series) in component state or a small store. No global state library needed.
- **Components**: `StandingsTable` (reused for overall and per-division), `WeeklyVPCells`, `VPChart`, `TeamSelector`/legend, `SeasonPicker`, layout/nav, and states (`Loading`, `Empty`, `ErrorState`).
- **Responsive strategy**: mobile-first. Tables scroll horizontally in a container with a sticky first column. The chart supports tap-to-highlight, legend toggles, and a reduced default of highlighted lines on small screens.
- **Styling**: Tailwind with design tokens (colors, spacing, radius) defined once; consistent light/dark tokens if dark mode is implemented.
- **Dev without backend**: an MSW (mock service worker) or fixture-based mock of the API, generated from the OpenAPI contract and `docs/fixtures/`, so frontend work can proceed in parallel with the backend.

## 10. Configuration and secrets

All via environment variables, documented in `.env.example`:

`DATABASE_URL` (default `sqlite:///./dev.db`), `SECRET_KEY`, `ESPN_S2`, `ESPN_SWID` (or per-league references), `CORS_ORIGINS`, `ENV`.

ESPN cookies are read only inside `providers/espn/` and must be redacted from all logs.

## 11. Testing strategy

- **Engine**: exhaustive unit tests from ACCEPTANCE 1.1 plus property-based tests (Hypothesis) for AC-VP-12/13.
- **Providers**: ESPN adapter tested against recorded fixtures in `docs/fixtures/espn/`; a small manual script can refresh fixtures from the real API, but tests never call ESPN.
- **Database/services**: run against SQLite by default locally, where each worktree gets its own throwaway databases so concurrent agents stay isolated; CI and production use Postgres. `scripts/dev-postgres.sh` starts a worktree-local Postgres for debugging Postgres-specific behavior.
- **API**: FastAPI `TestClient` tests including authorization matrices and golden JSON comparison.
- **Frontend**: Vitest + Testing Library for components; Playwright for the end-to-end smoke test, responsive screenshots, and axe accessibility checks.
- **Coverage**: pytest-cov (lines and branches) for the backend and vitest's v8 coverage for the frontend, both reported on every PR (section 13.5). Thresholds are enforced by CI, not just reported.
- **Workflow scripts**: `scripts/ship.sh`, the gate logic in `scripts/merge.sh`, and
  `scripts/cleanup.sh` are driven by `backend/tests/test_workflow_scripts.py`, which runs the real
  scripts in a throwaway git repo with a stub `gh` first on `PATH` and replays synthetic `gh`
  payloads (draft vs open, missing/pending/failing checks, governance paths, `--allow-governance`,
  merge methods, merged vs unmerged branches): AC-WF-07/08/09/13/15/23.

## 12. Design decisions and rationale

| Decision | Why |
|---|---|
| Pure VP engine | The scoring rules are the heart of the product; being pure makes them easy to test exhaustively and trivially reusable. |
| Store VP components, not just totals | Lets the UI explain why a team got its VP, and makes debugging disagreements with the league easy. |
| Recompute VP per week rather than incrementally | ESPN scores can be corrected after the fact; recomputing a whole week is cheap and always consistent. |
| Fractions in the engine, strings over the wire | Avoids float tie bugs and display drift. |
| Provider returns matchups, scores derived from them | Matches how ESPN reports data and works for most other providers. |
| Contract-first API with generated TS types | Lets backend and frontend agents work in parallel with a machine-checked contract. |
| Merge gate in a script, plus GitHub rulesets where available | GitHub cannot enforce branch rules on private repos on a free plan; the script makes the rules hold anyway, and rulesets add server-side enforcement where possible. |
| Reviewer is a separate agent that posts a review comment, and a human approves and merges | GitHub forbids self-approval, so the formal approval must be a human's; the reviewer's definition comes from `main`, so a PR cannot weaken the reviewer that judges it. |
| Draft PR on first commit, review only when marked ready | Reviewers never spend effort on half-finished work. |
| Governance files are human-merge only | Agents cannot loosen the rules or gates that bind them. |

## 13. Repository tooling, CI, and the PR workflow

### 13.1 Flow

```
 agent commits ──▶ pre-commit hooks (lint, format, types, secrets) ──fail──▶ fix, commit again
        │ pass
        ▼
 agent ──▶ scripts/ship.sh ──▶ pre-push hook runs tests ──▶ push branch
        │
        ▼
 author ──▶ open one draft PR (`gh` as the App identity) and fill in the description
        │ ... later commits: push with ship.sh again ...
        ▼
 task done ──▶ rebase on main ──▶ scripts/ship.sh --ready ──▶ PR ready + label `ready-for-review`
        │                                                    │
        │                          CI: pre-commit | backend
        │                              | frontend | coverage comment on the PR
        ▼
 orchestrator ──▶ scripts/review.sh <pr>  (fresh session, clean worktree, reviewer from main)
        │                 │
        │            exit 2: changes requested ──▶ author fixes, ship.sh --ready, new review (max 3 rounds)
        │ exit 0: no blocking issues
        ▼
 human ──▶ approve + merge (desktop, gh, or scripts/merge.sh) ──▶ rebase merge (or squash)
                    (gates: not draft, CI green, no governance files changed
                     unless a human runs merge.sh --allow-governance)
        │
        ▼
 cleanup ──▶ scripts/cleanup.sh ──▶ local branch + worktree deleted
             (GitHub deletes the remote branch; merge.sh runs cleanup for you,
              a merge made in the web UI needs cleanup.sh run by hand)
             never push to a merged branch: the push re-creates it, with no PR and no CI
```

### 13.2 Pre-commit hooks (`.pre-commit-config.yaml`)

| Stage | Hooks |
|---|---|
| commit | trailing whitespace, EOF newline, YAML/TOML/JSON validity, merge-conflict markers, large files, private keys, no commit to `main`; gitleaks secret scan; ruff (lint with fixes) and ruff-format on `backend/`; mypy (strict); prettier, eslint, and tsc on `frontend/` |
| push | backend tests (`pytest -x`), frontend tests (`vitest run`) |

Local hooks skip themselves while `backend/` or `frontend/` does not exist (before M0). Hooks that auto-fix leave the files modified and fail the commit; staging the fixes and committing again passes.

Nothing runs on `post-commit`: committing never pushes and never opens a pull request, so pushing (`scripts/ship.sh`) is an explicit step the author agent takes.

### 13.3 CI (`.github/workflows/ci.yml`)

Jobs (the names are the required status checks in the `main` ruleset):

| Job | What it does |
|---|---|
| `pre-commit` | `pre-commit run --all-files` (so skipped local hooks still fail the PR) |
| `backend` | `pytest` with coverage against Postgres; total >= 85%; VP engine (`app/domain/*`) 100% lines and branches; coverage XML uploaded |
| `frontend` | eslint, tsc, `vitest run --coverage` (thresholds in the vitest config), build; coverage summary uploaded |
| `coverage-report` | PRs only: downloads both coverage artifacts, builds one markdown report with `scripts/coverage_report.py`, writes it to the job summary, and posts or updates a single PR comment |

An end-to-end Playwright job is added in M6. The workflow's default token is read-only; only `coverage-report` gets `pull-requests: write`.

### 13.4 Scripts

| Script | Run by | Purpose |
|---|---|---|
| `scripts/ship.sh [--ready]` | author agent | Push the branch; `--ready` marks the PR ready and labels it |
| `scripts/review.sh <pr>` | orchestrator | Run the reviewer in a fresh session; posts a review comment; exit 0 no blocking issues, 2 changes requested, 1 error |
| `scripts/merge.sh <pr> [--rebase \| --squash] [--allow-governance]` | human | Verify the CI and governance gates and merge (rebase by default) |
| `scripts/cleanup.sh [--dry-run] [branch ...]` | human after a web-UI merge, or `merge.sh` | Delete local `agent/*` branches whose PR is merged, and remove their worktrees |
| `scripts/setup-github.sh` | repo owner, once | Repo settings, label, Actions token permissions, ruleset |
| `scripts/dev-postgres.sh [up\|url\|down]` | any agent | Start, locate, or stop a worktree-local Postgres for Postgres-specific work |
| `scripts/coverage_report.py` | CI | Combine backend (Cobertura XML) and frontend (vitest `json-summary`) coverage into markdown |

### 13.5 Coverage reporting

- Backend: `pytest --cov=app --cov-branch --cov-report=xml`; frontend: vitest with the `json-summary` reporter. Both are produced on every PR run.
- The PR comment shows lines and branches (backend), lines/statements/functions/branches (frontend), and the least-covered files. A comparison against the base branch is a possible later improvement.
- Reporting is not the only control: CI fails below the thresholds (SPEC 4.6).

### 13.6 Identities and trust boundaries

| Identity | Used for | Holds |
|---|---|---|
| Owner (human) | one-time setup, and approving and merging every PR | admin on the repo |
| Author identity (your account or your token) | agents pushing branches, opening PRs, and posting review comments; a human may run `scripts/merge.sh` | Contents + Pull requests: write |

There is **no separate reviewer account**. The reviewer agent runs in a fresh session and a clean worktree but with the author identity, so it can only post a review *comment*, never an approval; a human makes the formal approval and merge. The reviewer's agent definition is read from `main` and cannot be altered by the PR under review, and the reviewer treats PR text and code comments as untrusted input. Details are in `docs/GITHUB_SETUP.md`.

### 13.7 Known limits

- GitHub enforces branch rulesets only for public repos on the Free plan, or any repo on a paid plan. Otherwise the gate is `scripts/merge.sh` and agent discipline only (SPEC open question 9).
- `opencode run --agent` and the reviewer's permission syntax follow opencode's documented configuration; verify with the installed version (`opencode run --help`) during M0.
- The scripts and workflow have not been run against a live GitHub repo; the gate logic in `merge.sh` was exercised against synthetic payloads. The first end-to-end PR in M0 (AC-WF-21) is the real test.
