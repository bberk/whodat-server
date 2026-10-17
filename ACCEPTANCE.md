# ACCEPTANCE: Victory Points Fantasy Football Standings

> Status: DRAFT v0.1. Every criterion must be verifiable by an automated test unless marked (manual). Criteria IDs are stable; reference them in test names (e.g. `test_AC_VP_04_...`).
>
> Criteria tied to a **[DECISION]** or **[OPEN]** item in SPEC.md are marked and may change.

## 1. VP engine (pure function; unit tests, no I/O)

Input for a week: the list of teams with `team_id`, `points` (exact decimal), and `opponent_id` (or none for a bye). Output: per-team VP components and total.

| ID | Criterion |
|---|---|
| AC-VP-01 | H2H winner gets +1 for the H2H component; loser gets 0. |
| AC-VP-02 | If a matchup is tied, both teams get +0.5 for the H2H component. |
| AC-VP-03 | The top `floor(N/2)` scoring teams each get +1 top-half VP (no ties at the cutoff). |
| AC-VP-04 | The single highest scorer gets +1 for the high-score component. |
| AC-VP-05 | The single lowest scorer gets -1 for the low-score component. |
| AC-VP-06 | When k teams tie for the highest score, each gets `1/k` high-score VP. |
| AC-VP-07 | When k teams tie for the lowest score, each gets `-1/k` low-score VP. |
| AC-VP-08 | **[DECISION]** When teams tie across the top-half cutoff, they share equally the top-half points for the rank positions inside the cutoff. |
| AC-VP-09 | A team with no opponent (bye) gets no H2H component but still gets top-half/high/low components. |
| AC-VP-10 | Weekly total = H2H + top-half + high + low for every team. |
| AC-VP-11 | Score comparisons are exact: `123.40` equals `123.4`; values that differ only by float error are not treated as different. Scores are parsed from strings or Decimals, never compared as floats. |
| AC-VP-12 | Engine output is deterministic and independent of input ordering (property test: shuffling input yields identical per-team results). |
| AC-VP-13 | Property test: for any valid week, the sum of high-score VP is exactly +1, the sum of low-score VP is exactly -1, and the sum of H2H VP equals the number of completed matchups. |
| AC-VP-14 | The engine performs no I/O and imports nothing from the web, database, or provider layers (enforced by an import-boundary test or lint rule). |

### 1.1 Worked examples (must be encoded as test fixtures)

**Example A: baseline with a tied high score (6 teams, 3 top-half slots)**

Matchups: A vs F, B vs E, C vs D.

| Team | Points | H2H | Top half | High | Low | Total |
|---|---|---|---|---|---|---|
| A | 120 | +1 (beat F) | +1 | +0.5 | 0 | **2.5** |
| B | 120 | +1 (beat E) | +1 | +0.5 | 0 | **2.5** |
| C | 100 | +1 (beat D) | +1 | 0 | 0 | **2** |
| D | 90 | 0 | 0 | 0 | 0 | **0** |
| E | 80 | 0 | 0 | 0 | 0 | **0** |
| F | 70 | 0 | 0 | 0 | -1 | **-1** |

(A and B are not playing each other. They tie for the highest score, so the high-score VP is split: 0.5 each. This is the 2.5 VP case from the original rules description.)

**Example B: tie across the top-half cutoff [DECISION] (6 teams, 3 top-half slots)**

Matchups: A vs E, B vs F, C vs D (C and D tied).

| Team | Points | H2H | Top half | High | Low | Total |
|---|---|---|---|---|---|---|
| A | 130 | +1 | +1 | +1 | 0 | **3** |
| B | 120 | +1 | +1 | 0 | 0 | **2** |
| C | 100 | +0.5 (tied matchup) | +0.5 | 0 | 0 | **1** |
| D | 100 | +0.5 (tied matchup) | +0.5 | 0 | 0 | **1** |
| E | 80 | 0 | 0 | 0 | 0 | **0** |
| F | 70 | 0 | 0 | 0 | -1 | **-1** |

(C and D occupy ranks 3 and 4; only rank 3 is inside the cutoff, so each gets 0.5 top-half VP. They also tied their own matchup, so each gets 0.5 H2H.)

**Example C: tied low score**

Two non-opposing teams tied for the lowest score each get -0.5 low-score VP.

**Example D: three-way tie for the high score**

Three tied teams each get exactly 1/3 high-score VP (tests must use exact fractions, not rounded decimals).

## 2. Standings and tiebreakers

| ID | Criterion |
|---|---|
| AC-ST-01 | Season VP for a team equals the sum of its weekly VP over all completed regular-season weeks. |
| AC-ST-02 | Teams are ranked by season VP descending. |
| AC-ST-03 | **[DECISION]** Teams tied on VP are ordered by H2H wins descending; H2H ties do not count as wins. |
| AC-ST-04 | Teams still tied are ordered by total points for descending. |
| AC-ST-05 | Teams tied on all three keys share the same rank number. |
| AC-ST-06 | Division standings apply the same ranking rules, restricted to the division's teams; ranks are within the division. |
| AC-ST-07 | Overall rank is computed across all teams in the league for the season. |
| AC-ST-08 | **[DECISION]** Playoff weeks and incomplete weeks contribute no VP. |
| AC-ST-09 | Season totals that should be equal compare as equal even when built from fractional parts (e.g. 1/3 + 1/3 + 1/3 equals 1). |

## 3. Data sync and storage

| ID | Criterion |
|---|---|
| AC-DB-01 | After a sync, the database contains the league, owners, teams (with season and division), matchups, and scores for the requested season. |
| AC-DB-02 | Running the same sync twice produces identical database contents (no duplicates, no changed rows). |
| AC-DB-03 | If a provider reports a changed score for an already-synced week, the score is updated and VP for that whole week is recomputed for all teams. |
| AC-DB-04 | Each Score row stores total VP and the component breakdown (h2h, top-half, high, low). |
| AC-DB-05 | The same test suite passes against both SQLite and Postgres. |
| AC-DB-06 | A migration from an empty database to the latest schema succeeds, and downgrade/upgrade round-trips without error. |
| AC-DB-07 | Sync tests run entirely from recorded fixtures; the test suite makes no live ESPN calls. |
| AC-DB-08 | ESPN credentials (`espn_s2`, `SWID`) never appear in logs, error messages, API responses, or the repository. |

## 4. Provider abstraction

| ID | Criterion |
|---|---|
| AC-PR-01 | A `LeagueProvider` interface exists; the sync service depends only on it and on normalized data types. |
| AC-PR-02 | A `FakeProvider` (in-memory) exists and the entire sync → VP → standings pipeline is tested end to end using it, with no ESPN code involved. |
| AC-PR-03 | No module outside `providers/espn/` imports `espn_api` or contains ESPN-specific logic (enforced by an import-boundary test or lint rule). |
| AC-PR-04 | Adding a second provider requires no changes to the engine, models, API, or frontend. (Demonstrated by the `FakeProvider` being registered purely through the provider registry.) |

## 5. Accounts and authorization

| ID | Criterion |
|---|---|
| AC-AU-01 | A visitor can sign up with an email and password; duplicate emails are rejected (case-insensitively). |
| AC-AU-02 | Passwords are stored only as salted hashes (argon2id or bcrypt); no plaintext in the database or logs. |
| AC-AU-03 | A user can log in with valid credentials and is rejected with a generic error for invalid ones (no user enumeration). |
| AC-AU-04 | After signup, a user can be linked to an owner of a league (mechanism per SPEC **[OPEN]** Q3). |
| AC-AU-05 | A user can fetch standings only for leagues their owner belongs to; requests for other leagues return 403 or 404. |
| AC-AU-06 | Unauthenticated requests to league data endpoints return 401. |
| AC-AU-07 | Auth endpoints are rate limited (a test demonstrates throttling after repeated failures). |

## 6. API

| ID | Criterion |
|---|---|
| AC-API-01 | The endpoints in ARCHITECTURE.md exist and match the published OpenAPI spec. |
| AC-API-02 | The standings response for a known fixture league matches a checked-in golden JSON file exactly (ranks, VP, tiebreak ordering, weekly VP). |
| AC-API-03 | The cumulative VP response for a team at week W equals the sum of its weekly VP for weeks 1..W. |
| AC-API-04 | Invalid inputs (unknown season, week out of range) return 4xx with a structured error body, never a 500. |
| AC-API-05 | Standings for a 12-team, 18-week season respond in under 500 ms (p95) against SQLite in a local benchmark test. |

## 7. Frontend

| ID | Criterion |
|---|---|
| AC-FE-01 | A logged-in user sees the overall standings table with rank, team, owner, season VP, W-L-T, points for, and a VP column per week. |
| AC-FE-02 | Division standings render as one table per division with ranks within the division. |
| AC-FE-03 | The cumulative VP chart shows one line per team with week on the x-axis and cumulative VP on the y-axis; values match the API. |
| AC-FE-04 | Selecting a team highlights it in both the chart and the table; teams can be toggled in the chart. |
| AC-FE-05 | The layout is usable at 360px, 768px, and 1280px widths: no horizontal scrolling of the page body, wide tables scroll within their container with the team column pinned (Playwright screenshot tests at those widths). |
| AC-FE-06 | Loading, empty (no data yet), and error states are shown for each data view. |
| AC-FE-07 | Automated accessibility check (axe) reports no serious or critical violations on the login and standings pages. |
| AC-FE-08 | Unauthenticated users are redirected to login; after login they return to the page they requested. |
| AC-FE-09 | (manual) A human reviewer confirms the UI looks modern and polished on a real phone and a desktop browser. |

## 8. Repository and delivery

| ID | Criterion |
|---|---|
| AC-DX-01 | A fresh clone can run the app locally following README steps only (or `docker compose up`). |
| AC-DX-02 | CI runs `pre-commit` on all files, backend tests (on SQLite and Postgres), and frontend lint, type check, tests, and build on every pull request and every push to `main`, and they all pass on `main`. |
| AC-DX-03 | The VP engine module has 100% line and branch coverage (enforced in CI). |
| AC-DX-04 | Overall backend coverage is at least 85% (enforced in CI). |
| AC-DX-05 | No secrets are committed; `.env.example` documents every required variable. |

## 9. Development workflow and quality gates

| ID | Criterion |
|---|---|
| AC-WF-01 | `.pre-commit-config.yaml` exists and `pre-commit install` installs the commit, push, and post-commit hooks. |
| AC-WF-02 | The commit-time hooks include: ruff lint (with auto-fix), ruff format, mypy, eslint, tsc, prettier, secret scanning, and file-hygiene checks (whitespace, EOF, YAML/TOML/JSON validity, merge-conflict markers, large files, private keys). |
| AC-WF-03 | A commit containing a ruff violation (or a failing mypy, eslint, or tsc check) is rejected by the hooks. (Verified once by hand during M0 with a throwaway branch.) |
| AC-WF-04 | A commit made directly on `main` is rejected by the `no-commit-to-branch` hook. |
| AC-WF-05 | The pre-push hook runs the backend and frontend tests; a push with a failing test is rejected. |
| AC-WF-06 | CI runs `pre-commit run --all-files`, so a change that bypassed the local hooks still fails the PR. |
| AC-WF-07 | With `AGENT_AUTOSHIP=1`, a commit on an `agent/*` branch pushes the branch to origin and opens a draft PR if none exists; a second commit pushes without opening another PR. Without `AGENT_AUTOSHIP`, a commit pushes nothing. |
| AC-WF-08 | `scripts/ship.sh` refuses to run on `main`. |
| AC-WF-09 | `scripts/ship.sh --ready` marks the PR ready for review and adds the `ready-for-review` label. |
| AC-WF-10 | `scripts/review.sh <pr>` runs the reviewer in a new session on a clean worktree checked out at the PR head, with the reviewer definition taken from `main` rather than from the PR; the reviewer never sees the author's context. |
| AC-WF-11 | The review is submitted as a GitHub review comment on the PR's current head commit, stating a verdict (approved or changes requested) and listing the blocking issues, the non-blocking suggestions, and what was verified. |
| AC-WF-12 | The reviewer cannot modify files, push, or merge (enforced by its permission configuration). |
| AC-WF-13 | `scripts/merge.sh <pr>` squash-merges and deletes the branch only when the PR is open, not a draft, and all CI checks passed; it refuses a PR that changes governance files unless run with `--allow-governance`. Each unmet condition is tested and blocks the merge (synthetic-data tests of the gate logic). |
| AC-WF-14 | An independent review of an earlier commit does not count for a newer head: the review records the head commit it reviewed, and a push after a review requires a new review. |
| AC-WF-15 | A PR that changes governance files (`AGENTS.md`, `SPEC.md`, `ACCEPTANCE.md`, `ARCHITECTURE.md`, `.opencode/`, `.github/`, `scripts/`, `.pre-commit-config.yaml`) is not merged by `scripts/merge.sh` without `--allow-governance`, and only a human merges it. |
| AC-WF-16 | Every PR gets a single combined coverage comment covering the backend and the frontend, updated in place on each push, also written to the CI job summary. |
| AC-WF-17 | The coverage comment reports lines and branches for the backend, and lines, statements, functions, and branches for the frontend, and lists the least-covered files. |
| AC-WF-18 | CI fails when backend coverage is below 85%, VP engine coverage is below 100%, or frontend coverage is below its configured thresholds. |
| AC-WF-19 | (manual) The repo is configured per `docs/GITHUB_SETUP.md`: squash-only merges, branches deleted on merge, `ready-for-review` label exists, Actions token read-only. |
| AC-WF-20 | (manual, requires a public repo or paid plan) The `main` ruleset rejects direct pushes, force-pushes, and merges without passing required checks, and requires a pull request; required check names match the real CI job names. (No approval is required: a human approves and merges.) |
| AC-WF-21 | (manual) One trivial change goes through the whole loop successfully: commit, draft PR, ready, independent agent review, human squash merge. A second trivial change with a deliberate defect gets a changes-requested review. |

## 10. End-to-end smoke test

A single Playwright test using the `FakeProvider` and a seeded league must: sign up → link to an owner → view overall standings → view division standings → see the cumulative VP chart, with every number matching the golden fixture.

## 11. Definition of done for the whole project

All criteria above pass in CI, all **[OPEN]** questions in SPEC.md are resolved or explicitly deferred, and the owner has verified AC-FE-09, AC-WF-19 through AC-WF-21, and a real ESPN sync against their actual league (manual).
