# SPEC: Victory Points Fantasy Football Standings

> Status: DRAFT v0.1. Items marked **[DECISION]** are proposed defaults the human owner should confirm or change. Items marked **[OPEN]** are unresolved questions (see the end of this file).

## 1. Purpose

A website that shows fantasy football standings under a custom scoring system called **Victory Points (VP)**. ESPN's built-in standings only rank by win/loss record, so this site pulls league data from ESPN, computes VP, and displays standings and trends.

Members join a league with an invite code, may associate themselves with one of the league's owners, and can view that league's standings.

## 2. Goals

1. Accurately compute VP for every team, every week, per the rules in section 3.
2. Show overall and per-division standings, a per-week VP table, and a cumulative VP chart.
3. Work well on mobile and desktop browsers with a modern look.
4. Isolate ESPN-specific code behind an interface so another provider (Sleeper, Yahoo, manual CSV, etc.) can be added without changing the VP engine, database schema, API, or frontend.

## 3. Victory Points rules (authoritative)

Each regular-season week, every team earns VP from four components:

| Component | VP |
|---|---|
| Head-to-head (H2H) win | +1 |
| Score in the top half of the league that week | +1 |
| Highest score of the week | +1 |
| Lowest score of the week | -1 |

A team's weekly VP is the sum of its components. Season VP is the sum across weeks.

### 3.1 Tie handling (VP is split)

- **H2H tie** (two matched-up teams have identical scores): each team gets 0.5 VP for the H2H component.
- **Tie for highest score**: the 1 VP is split evenly among all tied teams (2 teams → 0.5 each; 3 teams → 1/3 each).
- **Tie for lowest score**: the -1 VP is split evenly among all tied teams (2 teams → -0.5 each).
- **Tie across the top-half cutoff** **[DECISION]**: the top-half VP is a pool of one point for each of the top `floor(N/2)` rank positions (N = number of teams). Teams tied across the cutoff share the points for the rank positions inside the cutoff equally. Example with N=6 (3 slots): scores 130, 120, 100, 100, 80, 70 → the two teams on 100 occupy ranks 3 and 4; only rank 3 is inside the cutoff, so each gets 0.5 top-half VP.

Splitting is exact (fractions such as 1/3 are possible). See ACCEPTANCE.md for worked examples.

### 3.2 Standings ranking

Teams are ranked by, in order:

1. Total season VP (descending)
2. Total H2H wins in the season (descending) **[DECISION]** H2H ties do not count as wins.
3. Total points for in the season (descending)

If all three are equal, teams share the same rank (display order is then alphabetical by team name, but the rank number is shared).

### 3.3 Which weeks count **[DECISION]**

- VP is computed for **completed regular-season weeks only**. Playoff weeks are displayed (if at all) but earn no VP.
- A week is "completed" when ESPN reports the matchup period as finished.
- Bye weeks or teams without an opponent: still earn the top-half / high / low components; no H2H component.

## 4. Functional requirements

### 4.1 Data ingestion

- Fetch league data from ESPN: league metadata, owners, teams (per season, including division), weekly matchups, and weekly scores.
- Sync is **idempotent**: re-running it never creates duplicates and updates any changed values (ESPN scores can be corrected after the fact). After a sync, VP is recomputed for any affected weeks.
- Sync is runnable on demand via a CLI command, and schedulable via cron or equivalent.
- Private ESPN leagues require ESPN auth cookies (`espn_s2`, `SWID`). A league admin supplies them
  when adding the league; they are stored encrypted at rest on that user's membership and decrypted
  only on the provider call path. They are never committed, never logged, and never returned by the
  API.
- Adding a league validates the credentials by constructing an ESPN league object before anything is
  stored; a failed validation stores nothing.
- A league-wide refresh can be triggered from the UI by a member whose membership holds credentials.
  Refresh is rate limited per league and per user; members without credentials cannot refresh.
- Historical seasons can be backfilled by specifying a season.
- The environment-level `ESPN_S2`/`ESPN_SWID` path remains available for CLI and bootstrap use only.

### 4.2 Data storage

Persisted entities (see ARCHITECTURE.md for the schema):

- **League** (and metadata, including provider and external ID)
- **Owner**
- **Team** (per season; includes division and owner)
- **Matchup** (season, week, home team, away team)
- **Score** (team, season, week, points, victory points and its component breakdown)
- **User** (email, password hash, role)
- **Invite** (league, code hash, role, expiry)
- **Membership** (user, league, optional owner association, encrypted ESPN credentials)

The database engine must be swappable between SQLite and Postgres with no application code changes (config only).

### 4.3 Provider abstraction

All ESPN-specific code lives behind a provider interface that returns normalized data. Adding a new provider must require only: a new adapter module, registration of the provider, and no changes to the VP engine, database schema, API, or frontend.

### 4.4 Accounts and access

- Accounts are invite-only: signing up requires a valid, unexpired shared invite code, which is
  validated against its stored hash. Invites belong to a league, default to a 7-day expiry, and
  carry either the **admin** or **member** role. The raw code is shown only once when an admin
  creates the invite and is never retrievable afterwards; regenerating means creating a new invite.
- Users and leagues are many-to-many. A membership row links a user to a league, optionally records
  that user's owner (team) association, and stores that user's ESPN credentials, encrypted at rest.
- An admin can add a league by providing `espn_league_id`, an optional season, and optional
  ESPN_S2/ESPN_SWID. The backend validates by constructing an ESPN league object before storing
  anything; on success it stores the league, the membership, the encrypted credentials, and syncs
  the requested season. A member can add only an existing league by `espn_league_id` and joins
  without credentials; a member supplying credentials is rejected.
- Credentials are encrypted at rest with AES-256-GCM under `LEAGUE_CREDENTIALS_KEY`, decrypted only
  on the provider call path, and never logged or returned by the API. The environment
  ESPN_S2/ESPN_SWID path remains for CLI and bootstrap use only.
- A member whose membership holds credentials can trigger a league-wide refresh from the UI; refresh
  is rate limited per league and per user. Members without credentials cannot refresh.
- After joining, a user may associate their membership with one of that league's owners.
- Not in v1: email verification, password reset, social login, claiming more than one owner in a
  league.

### 4.5 Frontend

Pages and views:

1. **Sign up (invite code) / Log in**
2. **Standings**
   - Season selector (default: current season).
   - **Overall standings table**: rank, team, owner, season VP, H2H record (W-L-T), points for, and one column per week showing that week's VP.
   - **Division standings**: one table per division; the division only filters and groups the rows, and the rank displayed for each team is its overall league rank.
   - Tapping/clicking a team highlights it in the chart.
3. **VP chart**: a line chart of cumulative VP over time, x-axis = week, one line per team. Users can highlight a team and toggle teams on and off. Must be legible on a phone.

UI requirements:

- Responsive: usable on phones (~360px wide) through desktop.
- Modern, clean visual design; light and dark mode is nice to have, not required.
- Wide tables scroll horizontally inside their own container, with the team column pinned (sticky).
- Accessible: sufficient color contrast, keyboard navigable, chart series distinguishable without relying on color alone (e.g., highlight on select, labels).
- Meaningful loading, empty, and error states.

### 4.6 Development workflow and quality gates

How code gets into `main` is part of the product's requirements, because the code is written by a swarm of agents and the workflow is what keeps quality independent of any single agent.

1. **Pre-commit checks.** Every commit runs `pre-commit` hooks: ruff lint and format and mypy for the backend; eslint, tsc, and prettier for the frontend; secret scanning; basic file hygiene; and a block on committing directly to `main`. Tests run on push. Hooks may not be bypassed (`--no-verify`, `SKIP`), and CI re-runs all hooks on the whole repo.
2. **Branch per task, PR per branch.** Work happens on `agent/<task-id>-<slug>` branches. After each commit by an agent, the branch is pushed to origin and a **draft** pull request is opened if none exists. Draft PRs are not reviewed. The author marks the PR ready when the task meets its definition of done.
3. **Independent review.** A ready PR is reviewed by a different agent that shares no context with the author: a new session, a clean checkout, and reviewer instructions taken from `main` rather than from the PR. The reviewer judges the change against the project docs and the acceptance criteria and posts its verdict (approved or changes requested) and what it verified as a review comment. GitHub does not let an author approve a PR, so the reviewer reports and a **human** makes the formal approval.
4. **Merge.** A human approves and merges every ready PR — rebase by default, or squash — after CI is green and the independent review has run on the current head commit; the branch is then deleted. The ruleset requires linear history, so there are no merge commits. Agents never merge, and never merge their own work. Changes to the rules and gates themselves (the four spec documents, `.github/`, `.opencode/`, `scripts/`, `.pre-commit-config.yaml`) are never auto-merged and always need a human.
5. **Coverage reporting.** CI measures coverage for the backend and the frontend and posts a combined report as a comment on each PR, updated on every push. Thresholds: backend total >= 85% (lines and branches measured), VP engine 100% (lines and branches), frontend thresholds as configured in its test runner **[DECISION]** (proposed starting point: 80% lines and statements).
6. **GitHub setup.** Repo settings (squash and rebase merges, linear history, branch cleanup) and a ruleset on `main` requiring a pull request and passing CI are set up once by the owner. No approval is required, because a human makes every approval and merge and GitHub forbids self-approval; the reviewer agent only reports. No second account or reviewer token is needed. See `docs/GITHUB_SETUP.md`. Server-side enforcement depends on repo visibility and plan (see Q9).

## 5. Non-functional requirements

- **Correctness over cleverness**: the VP engine is pure, deterministic, and exhaustively tested.
- **Numeric safety**: scores are compared as exact decimals, VP is computed with exact fractions; never use binary floating point for score or VP comparison.
- **Security**: passwords hashed with a modern algorithm (argon2id or bcrypt); secrets from environment only; authorization enforced server-side on every league-scoped endpoint; basic rate limiting on auth endpoints.
- **Performance**: standings for a 12-team, 18-week season respond in under 500 ms (p95) on a modest host.
- **Portability**: `docker compose up` (or equivalent documented steps) brings up a working local dev environment.

## 6. Out of scope for v1

Live in-game score updates, playoff VP, trade/transaction tracking, push notifications, league commissioner admin UI, non-ESPN providers (only the interface), payments, public (unauthenticated) league pages.

## 7. Proposed tech stack **[DECISION]**

The owner has no hard requirements and limited frontend experience, so this favors mainstream, well-documented tools that agents write reliably.

- **Backend**: Python 3.15, FastAPI, SQLAlchemy 2.x + Alembic migrations, Pydantic. Python lets the ESPN adapter use the `espn-api` library (cwendt94/espn-api), which the legacy implementation used, directly.
- **Database**: SQLite for local dev and tests; Postgres for CI and production. Same code for both.
- **Frontend**: React + TypeScript + Vite, Tailwind CSS, a component library such as shadcn/ui, Recharts for the chart, TanStack Query for data fetching.
- **API contract**: FastAPI's generated OpenAPI spec; frontend types are generated from it.
- **Tooling**: `uv` (Python), `pnpm` (frontend), `pytest` + `pytest-cov`, `ruff`, `mypy`, `vitest` + coverage, `eslint`, `prettier`, Playwright (a small number of end-to-end tests), `pre-commit`, GitHub Actions for CI, the `gh` CLI for PR automation.

## 8. Suggested milestones

1. **M0 Skeleton**: repo layout, tooling, a passing "hello" test in both backend and frontend, DB migrations running, pre-commit hooks installed and passing, CI green with the coverage comment working, and the GitHub setup from `docs/GITHUB_SETUP.md` done and verified with one trivial end-to-end PR (commit, draft PR, review, merge). Do this before any parallel work starts.
2. **M1 VP engine**: pure module plus the full unit test suite from ACCEPTANCE.md (no I/O).
3. **M2 Data layer + provider interface**: schema, repositories, `LeagueProvider` interface, a fake in-memory provider for tests.
4. **M3 ESPN adapter + sync**: real ESPN adapter, sync CLI, idempotency tests (using recorded fixtures, not live calls).
5. **M4 API + auth**: standings endpoints, invite signup, memberships, league credentials, owner
   association, authorization tests.
6. **M5 Frontend**: login, standings tables, chart, responsive polish (can start on stubbed API data once the API contract exists).
7. **M6 Hardening**: end-to-end tests, docs, Docker Compose, deployment notes.

## 9. Open questions **[OPEN]**

Agents must not guess on these. Record any new ones in `docs/OPEN_QUESTIONS.md`.

1. **Top-half ties across the cutoff**: confirm the proposed splitting rule in 3.1.
2. **Odd number of teams**: is top half `floor(N/2)` (proposed) or something else?
3. **Owner linking** *(resolved)*: a user joins a league with an invite code, then may associate their
   membership with one of that league's owners; the association is optional and limited to the
   caller's own membership.
4. **Account features** *(resolved)*: one user can belong to multiple leagues through memberships.
   Password reset remains out of scope for v1.
5. **Do H2H ties count toward the "wins" tiebreaker?** (Proposed: no.)
6. **Playoff weeks**: confirm no VP is awarded in the playoffs.
7. **Hosting target**: affects scheduling (cron vs in-process scheduler) and the Postgres choice.
8. **Number of leagues and seasons** the site needs to support at launch (assumed: one league, with the option to backfill past seasons).
9. **Repo visibility and GitHub plan** *(resolved)*: **public repo on the Free plan**. GitHub enforces branch rulesets there at no cost, and the pre-commit secret scan plus a full-history check keep secrets out (see `docs/GITHUB_SETUP.md`). A private repo on Free would have no server-side enforcement.
10. **Reviewer identity** *(resolved)*: the reviewer is a separate agent that posts a fresh-eyes review comment; **a human approves and merges every PR**. GitHub forbids self-approval, so no second account is used and the ruleset does not require an approval.
11. **Who triggers review and merge** *(resolved)*: the orchestrator runs `scripts/review.sh <pr>` after a PR is marked ready; a **human** then reads the report and the CI result and approves and merges. `scripts/merge.sh` remains available to a human as a guarded merge helper.
