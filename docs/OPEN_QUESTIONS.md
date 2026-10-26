# Open questions and deviations

Agents append an entry here (instead of guessing) when a spec document is wrong, missing, or
ambiguous, or when implementation deviates from a document. Each entry records: what was found,
the options, a recommendation, and what was done in the meantime.

Follow the format used below. Newest entries at the top.

---

## OQ-0018 — The Elo chart no longer marks cup weeks

- **Found:** `ACCEPTANCE.md` AC-Elo-09/17/20, `ARCHITECTURE.md`, and `SPEC.md` described
  cup-week chart markers and cup-specific chart text. The human product decision for the Elo
  history chart is the opposite: cup weeks must not get markers, labels, or annotations in the
  graph, while cup-week scoring stays unchanged and exact values remain available in the
  accessible data table.
- **Options:** (1) keep cup markers and the old criteria; (2) remove cup markers and annotations
  from the chart and update the governance wording to match.
- **Recommendation:** option 2. It matches the requested product behaviour and keeps the
  `<details>` table as the chart's exact-value non-visual equivalent.
- **In the meantime:** cup markers, cup vertical rules, "Cup" labels, cup summary notes, and
  `(cup)` table/select annotations were removed. Cup-week scoring is unchanged; a cup week that
  changes a series value remains visible in the accessible data table without a cup annotation.
- **Follow-up:** none; this entry records that it supersedes the old cup-marker requirement.

---

## OQ-0017 — Two latest releases cannot be adopted without breaking the toolchain

- **Found:** The 2026-10-25 dependency audit (`docs/DEPENDENCY_AUDIT.md`) found two latest stable
  releases that the current graph cannot use: TypeScript 7.0.2 (`typescript-eslint@8.72.0` requires
  `typescript <6.1.0`) and `idna` 3.20 (`espn-api==1.0.1` requires `idna>=3.15,<3.16`).
- **Options:** (1) force the newer packages and lose lint or dependency resolution; (2) keep the
  newest compatible versions and revisit when the upstream constraints widen.
- **Recommendation:** option 2. Neither current version has an open advisory, and the upgrades in
  this change already close every known application vulnerability.
- **In the meantime:** TypeScript stays at 5.9.3, `idna` at 3.15, and Postgres at 18 (19 is still an
  RC). `docs/DEPENDENCY_AUDIT.md` records the exact blockers and follow-ups.

---

## OQ-0016 — History uses a week-granularity time window instead of a season-only filter

- **Found:** `ACCEPTANCE.md` AC-Elo-17 and `SPEC.md` describe the History chart's season filter as
  a control that defaults to All history. The UI task requires a dynamic time window at week
  granularity: From/To week selects labelled with season and week, plus All history, Current
  season, and Last 12 weeks presets.
- **Options:** (1) keep only the per-season buttons and add a separate From/To range; (2) replace
  the season buttons with one window control whose presets include All history and Current season,
  and let From/To cover any single-season view; (3) expose both a season control and a week range.
- **Recommendation:** option 2. It satisfies week granularity without duplicating two competing
  range controls, and All history remains the default.
- **In the meantime:** `HistoryPage` renders the window control. A single-season view is still
  reachable through Current season or by selecting that season's first and last weeks; the current
  ratings table always shows every team and is never filtered. No API or response shape changed.
- **Follow-up:** update AC-Elo-17/SPEC wording at the next governance edit to describe the window
  control and its presets.

---

## OQ-0015 — Clinch search is deliberately conservative at its score-ranking bounds

- **Found:** Proving X/Y/Z/E exactly could require enumerating every remaining score ordering and
  every tie group, not only H2H results. For a 12-team league with four weeks left, the full
  combinatorial space is impractical for a read endpoint, and the owner explicitly requires no
  false badge when a node/time cap is hit.
- **Options:** (1) enumerate all score orderings exactly with a cap, accepting that most 12-team
  late seasons would hit the cap and show no badges; (2) enumerate all H2H outcomes exactly while
  bounding each team's non-H2H VP between its feasible weekly extremes (-1 and +2), then return no
  designation if a per-team node cap is exhausted; (3) show approximate ESPN playoff percentages.
- **Recommendation / owner-confirmed constraints:** option 2. Points-for ties stay undecided,
  missing metadata/schedule produces no badge, and a cap never yields a provisional result.
- **In the meantime:** `app/domain/clinch.py` enumerates every non-cup H2H home-win/away-win/tie
  outcome while independently bounding rank VP components. The independent bound can withhold a
  designation that a fully correlated score-order search might prove, but cannot invent one. The
  default per-team node cap is 5,000 and exhaustion returns `null` for that team. This behavior is
  documented in SPEC 3.6 and ARCHITECTURE 7.1; no schema migration is required because playoff
  metadata is stored in the existing `league_season.metadata` JSON.

---

## OQ-0014 — WAPDate elimination ignores points for and uses fixed period end weeks

- **Found:** The confirmed WAPDate rule greys a team in the current period when another team can
  no longer finish below it on VP and wins. The bound ignores points for, even though points for
  is the final ordering key, and it uses `end_week - highest_completed_week` as the remaining-week
  count even when a short regular season ends before a period's end week.
- **Decision (owner-confirmed):** follow the stated rule: VP and wins only, fixed period end weeks,
  and weeks 13+ ignored. The domain function documents that the flag means "no other team can beat
  this team on the period's VP and wins", not a guarantee about points for.
- **In the meantime:** `app/domain/wapdate.py` implements the bound and its tests pin the equality
  and cup-week cases. No schema or migration change.

---

## OQ-0013 — `braces` <=3.0.3 advisory accepted until Tailwind updates it

- **Found:** `pnpm audit` reports GHSA-vfj7-8cjw-p6xm (high, stack-exhaustion DoS via deeply nested
  patterns) for `braces` 3.0.3, reached only through Tailwind (`tailwindcss > micromatch/fast-glob/
  chokidar > braces`). The advisory has no patched release, so no `pnpm.overrides` entry can clear it.
- **Assessment:** Node is build/dev tooling only here; production serves Python plus static files on
  nginx. Tailwind runs at build time on repository-owned source, so the glob patterns `braces`
  parses are not attacker-controlled at runtime.
- **In the meantime:** accepted for now. The other frontend audit finding,
  `postcss-selector-parser` <7.1.6, was fixed with a pnpm override to `^7.1.6`.
- **Review trigger:** re-check `pnpm audit` when Tailwind ships an update that moves off
  `braces` 3.0.3, and remove the acceptance once a patched path exists.

---

## OQ-0012 — `provider_config_ref` is a legacy pointer whose value is "membership"

- **Found:** `ARCHITECTURE.md` §4 describes `provider_config_ref` as a pointer to environment-level
  bootstrap credentials. League credentials now come from memberships, where they are encrypted, so
  no environment-level pointer is used.
- **Decision:** keep the column and store the fixed non-secret value `"membership"` as a legacy
  marker that credentials come from memberships. The schema is unchanged and no migration is needed.
- **In the meantime:** league sync and league creation write `"membership"`.

---

## OQ-0011 — The API does not expose weekly VP components for the breakdown table

- **Found:** The existing standings UI showed a weekly VP breakdown with H2H, top-half, high-score,
  and low-score components. `docs/openapi.json` (`GET .../standings` and `GET .../vp-history`)
  exposes only each team's weekly VP totals and cumulative VP; it has no per-component fields, and
  the old values lived only in the isolated frontend mock.
- **Options:**
  1. Add weekly component fields to the standings or VP-history response. That changes the shared
     API contract and needs human approval.
  2. Keep the weekly breakdown as a week selector with each team's weekly VP and cumulative VP,
     using only fields the API returns.
  3. Remove the weekly breakdown section until components are exposed.
- **Recommendation:** option 2 now; option 1 later if users need to see why a week's VP was
  awarded.
- **In the meantime:** the frontend integrates against the real API. The separate weekly breakdown
  section was later removed at the owner's request, so weekly VP now appears only as the overall
  standings table's one-column-per-week values (option 3); no component value is invented.

---

## OQ-0010 — Shared-rank gap semantics for the M4 standings engine

- **Found:** `SPEC.md` §3.2 and AC-ST-05 say teams tied on all three keys "share the same rank
  number", but they do not say whether the ranks after a tied group skip the tied positions. The
  amended AC-ST-06/AC-FE-02 fix the division display (each row shows the overall league rank, with
  no division-local re-ranking) but still do not name the rank-gap convention.
- **Options:** (1) standard competition ranking, with gaps after a tied group (1, 2, 2, 4);
  (2) dense ranking, with no gaps (1, 2, 2, 3); (3) some other convention chosen by the owner.
- **Recommendation:** option 1. It is the conventional fantasy-standings reading of "share the same
  rank number" and matches the M4 engine.
- **In the meantime:** `backend/src/app/domain/standings.py::rank_teams` implements standard
  competition ranking and the tests pin it (`test_AC_ST_05_rank_gap_follows_tied_group`). The
  function stays generic over any subset of rows, but production division tables pass the overall
  rows and only group them by division, so the displayed rank is the overall league rank per
  amended AC-ST-06.

---

## OQ-0009 — Agents open PRs with `gh` as the App identity, not the GitHub MCP server

- **Found:** the GitHub MCP server fails with `401` (OQ-0006), and agents now commit, push, and act
  through the `brads-bots` GitHub App (`scripts/bot-identity.sh`). Routing PR creation through MCP
  would need a second credential configured outside the repo.
- **Change (owner decision):** author agents open, update, and inspect PRs with
  `scripts/bot-identity.sh run gh ...`. There is no MCP fallback. `gh` also adds the
  `ready-for-review` label, which MCP could not. Updated: `AGENTS.md`, `ACCEPTANCE.md` (AC-WF-22),
  `ARCHITECTURE.md` (the author-agent flow), `.opencode/pull-requests.md`, `scripts/ship.sh`, and
  `docs/GITHUB_SETUP.md`.
- **Supersedes:** the MCP-first procedure in OQ-0005 and the fallback in OQ-0006. OQ-0006's
  diagnosis still stands for the global MCP config, which is now unused by the agents.
- **Note:** these are governance and source-of-truth files, so a human merges the change.

---

## OQ-0008 — The autoship post-commit hook is removed

- **Found:** `.pre-commit-config.yaml` wired a `post-commit` hook to `scripts/ship.sh --post-commit`,
  which pushed the branch when `AGENT_AUTOSHIP=1`. After OQ-0005 made `ship.sh` push-only, that was
  its whole job. It also fired the pre-push hook — the full backend and frontend test suites — on
  *every commit*, and it was redundant: the author agent has to push anyway, because the PR tools
  need the branch on the remote and `scripts/review.sh` refuses an unpushed head.
- **Change (owner decision):** remove the autoship mechanism. `.pre-commit-config.yaml` keeps only
  the commit and push stages; `scripts/ship.sh` drops `--post-commit` (and `AGENT_AUTOSHIP`), keeps
  its `main` guard, and now rejects any unknown flag with a usage error. `scripts/review.sh` drops
  its `unset AGENT_AUTOSHIP` guard. Pushing is an explicit step before opening or updating the PR.
- **Impact:** `ACCEPTANCE.md` AC-WF-01 and AC-WF-07, `AGENTS.md` (install command and the pushing
  paragraph), `ARCHITECTURE.md` §2 tree and §13.1/§13.2/§13.4, `README.md`, `docs/GITHUB_SETUP.md`
  §5, `.opencode/pull-requests.md`, and `backend/tests/test_workflow_scripts.py`.
- **In the meantime:** implemented as above. The three `post_commit_*` tests were replaced by an
  explicit-push test, a later-commit push test, a "committing alone pushes nothing" test, a
  "`--post-commit` is rejected" test, and a check that the hook config has no `post-commit` stage.

---

## OQ-0007 — Merge method: rebase by default, squash available, no merge commits

- **Found:** the repo was configured squash-only (`scripts/setup-github.sh`) and `scripts/merge.sh`
  always passed `--squash`, so a long branch's history was always flattened into one commit.
- **Change (owner decision):** allow **squash and rebase** merges. The owner kept the ruleset's
  `required_linear_history` rule, so **merge commits remain impossible**; `scripts/merge.sh` now
  defaults to `--rebase`, accepts `--squash`, and rejects `--merge` with a pointer to the ruleset.
- **Impact:** `scripts/setup-github.sh` (rebase enabled), the live repo setting, `scripts/merge.sh`,
  `ACCEPTANCE.md` (AC-WF-13/19/21), `SPEC.md` §4.6 items 4 and 6 and §8, `AGENTS.md`,
  `ARCHITECTURE.md` §13, `docs/GITHUB_SETUP.md`, `.opencode/pull-requests.md`, and
  `backend/tests/test_workflow_scripts.py`.
- **In the meantime:** implemented as above. A rebase merge keeps the branch's own commit messages, so
  the PR title is no longer always a commit subject; the docs now say the title must still follow the
  commit rules because it is what appears in `git log`.

---

## OQ-0006 — The GitHub MCP server returns HTTP 401

- **Found:** the globally configured GitHub MCP server (`https://api.githubcopilot.com/mcp`, in
  `~/.config/opencode/opencode.json`) fails every call with `HTTP 401 ... token authentication
  failed`, including `get_me`. The PR-authoring procedure (OQ-0005) prefers those tools, so PRs
  cannot be opened that way until the credentials are fixed.
- **Impact:** author agents fall back to `gh`, which is authenticated in the agent environment. The
  work still gets done; only the preferred mechanism is unavailable.
- **Options:** (1) re-authenticate the MCP server (owner action) and keep the MCP tools as the
  preferred path; (2) drop the dependency and prescribe `gh` everywhere; (3) leave the MCP tools as
  a best-effort preference that silently falls back.
- **Recommendation:** option 1. Option 3 is what the guide documents, but it also requires the agent
  to report the failure rather than hide it.
- **In the meantime:** `.opencode/pull-requests.md` documents the `gh` fallback and asks the agent to
  report an MCP failure; AC-WF-22 accepts either path.

---

## OQ-0005 — The author agent opens the PR; `scripts/ship.sh` only pushes

- **Found:** `scripts/ship.sh` created the draft PR from `.github/pull_request_template.md`
  verbatim, so every PR started with empty placeholder sections and had to be filled in by hand
  afterwards. The post-commit hook runs in a shell with no model, so it cannot write a description.
- **Change (owner decision):** `scripts/ship.sh` and the `post-commit` hook now **push only**. The
  author agent opens the draft PR with the GitHub MCP tools (`tools.github.create_pull_request`,
  which supports `draft: true`) and fills in the body, following the new
  `.opencode/pull-requests.md`. `scripts/ship.sh --ready` still marks the PR ready and adds the
  `ready-for-review` label, because the GitHub MCP server exposes no tool for labels.
- **Impact:** AC-WF-07 no longer mentions opening a PR; AC-WF-22 records the new author
  responsibility. Updated: `scripts/ship.sh`, `AGENTS.md`, `ACCEPTANCE.md`, `ARCHITECTURE.md`
  (sections 2, 11, 13), `docs/GITHUB_SETUP.md`, `README.md`, and
  `.github/pull_request_template.md`.
- **Note:** all of these are governance files, so a human must merge the change. The GitHub MCP
  server must stay configured for author agents, or no PRs will be opened.
- **Superseded in part:** the `post-commit` hook itself was removed in OQ-0008. `ship.sh` is now run
  explicitly by the author agent; there is no hook stage that pushes.

---

## OQ-0004 — Workflow-script tests are not implemented

- **Found:** `ACCEPTANCE.md` AC-WF-07 and AC-WF-13 require tests of the workflow scripts' behavior,
  and `ARCHITECTURE.md` section 11 claimed the `scripts/merge.sh` gate logic "is tested against
  synthetic `gh pr view --json` payloads". No such tests exist: the only tests in the repo are under
  `backend/tests/` and `frontend/src/App.test.tsx`. Both scripts call `gh` inline, so they cannot be
  tested without a seam.
- **Impact:** AC-WF-07 and AC-WF-13 are implemented but unverified by the suite.
- **Options:**
  1. Add a payload seam (for example `MERGE_PR_JSON`/`SHIP_PR_JSON`) so a pytest module can drive
     the scripts against synthetic `gh pr view --json` output.
  2. Test the scripts end to end against a throwaway repository (slow, needs network).
  3. Accept manual verification only.
- **Recommendation:** option 1, as part of finishing M0.
- **Resolved (2026-10-17):** option 1, without changing the scripts.
  `backend/tests/test_workflow_scripts.py` runs the real `ship.sh` and `merge.sh` in a throwaway git
  repository with a stub `gh` first on `PATH`, so the gates are driven from synthetic
  `gh pr view --json` payloads: pushing the branch and later commits, refusal on `main`, `--ready`
  (ready + label), draft and closed PRs, no/pending/failing checks, every governance path,
  `--allow-governance`, and the merge-method flags. Covers AC-WF-07, AC-WF-08, AC-WF-09, AC-WF-13,
  and AC-WF-15. (The `AGENT_AUTOSHIP` cases were replaced when the hook was removed; see OQ-0008.)

---

## OQ-0003 — Runtime versions moved to Python 3.15, Node 26, and Postgres 18

- **Found:** `SPEC.md` §7 proposed **Python 3.12**, and CI pinned **Node 22** and **Postgres 16**.
  The owner asked to move to the newest stable runtimes.
- **Change:** backend `requires-python = ">=3.15"`, ruff `target-version = "py315"`, mypy
  `python_version = "3.15"`, `backend/Dockerfile` base `python:3.15-slim`; CI
  `actions/setup-node` `node-version: 26`; `frontend/package.json` `engines.node >= 26`;
  `postgres:16` → `postgres:18` in `docker-compose.yml` and CI; README and `SPEC.md` §7 updated
  to match.
- **Verified:** `uv sync`, `pytest` (11 passed, 100% coverage), `ruff check`/`format`, and
  `mypy --strict` all pass on CPython 3.15.0; the `python:3.15-slim`, `node:26-slim`, and
  `postgres:18` images exist.
- **Note:** `SPEC.md` is a source-of-truth document. This edit was made at the owner's direction
  and, like all governance changes, still needs a human merge.
- **In the meantime:** implemented as above.

---

## OQ-0001 — Reviewer identity: independent GitHub account vs an orchestrator reviewer agent

- **Found:** `AC-WF-10`/`AC-WF-11` require the review to be submitted as a **GitHub** review by an
  identity different from the PR author, and `SPEC.md` **[OPEN]** Q10/Q11 assume a second GitHub
  machine account plus `scripts/review.sh`/`scripts/merge.sh`. The owner wants the reviewer to be
  an agent run through the orchestrator (orchestrator.inc) instead of a second GitHub account.
- **Constraint:** Per the orchestrator docs, "Orchestrator's approval is never a GitHub approval"
  and its reviewer "does not approve or merge by itself." So an orchestrator reviewer cannot
  satisfy a GitHub ruleset that requires one non-author approval, and `scripts/merge.sh` (which
  requires a non-author GitHub approval on the current head) would block every merge.
- **Options:**
  1. Keep the second GitHub account; the orchestrator merely *schedules* `scripts/review.sh`.
     Preserves server-side enforcement (AC-WF-10/11/13 as written).
  2. Orchestrator reviewer only, no second account. Relies on orchestrator's verdict plus
     required **status checks** (drop the "1 approval" ruleset requirement), merging via
     `ao pr merge`/the desktop. Requires editing `scripts/setup-github.sh`, `scripts/merge.sh`,
     and AC-WF-10/11/13 — all governance files, so a human must merge.
  3. Hybrid: orchestrator reviewer for feedback, plus a second account as the formal approver.
- **Recommendation:** If avoiding a second GitHub account matters more than server-side
  enforcement, take option 2 and accept the weaker gate (documented in `docs/GITHUB_SETUP.md`).
- **In the meantime:** M0 keeps the existing design (options 1/3 remain valid). No spec change made.
- **Resolved (2026-10-17, owner decision):** option 2 with the repo's own reviewer kept. **Humans
  approve and merge every PR**; a separate agent posts a fresh-eyes review comment through
  `scripts/review.sh` (no second account, no `REVIEWER_GH_TOKEN`). The `main` ruleset no longer
  requires an approval, because GitHub forbids self-approval and a human is the formal approver.
  Updated: `SPEC.md` §4.6 items 3/4/6 and Q9–Q11, `ACCEPTANCE.md` AC-WF-10/11/13/14/15/20/21,
  `ARCHITECTURE.md` §12/§13, `AGENTS.md`, `scripts/setup-github.sh`, `scripts/merge.sh`,
  `scripts/review.sh`, `.opencode/agents/reviewer.md`, and `docs/GITHUB_SETUP.md`. All of these are
  governance files, so a human must merge the change.

## OQ-0002 — M0 skeleton decisions

- **Found:** `SPEC.md` §8 defines M0 as "repo layout, tooling, a passing 'hello' test in both
  backend and frontend, DB migrations running, pre-commit hooks installed and passing, CI green
  with the coverage comment working." That leaves some implementation details unstated.
- **Decisions taken in M0 (conservative, reversible):**
  - The initial Alembic revision `0001_baseline` is a **no-op**; the real schema is milestone M2.
  - `backend/src/app/domain/` and the other packages are created with docstring-only
    `__init__.py` files so the layout exists and the VP-engine coverage check passes trivially
    before M1 adds real code.
  - Frontend `pnpm-lock.yaml` must be generated on a machine with `pnpm` installed
    (`pnpm install`) before CI (`pnpm install --frozen-lockfile`) can pass.
- **Recommendation:** proceed with M1 after M0's end-to-end PR is verified (AC-WF-21).
- **In the meantime:** implemented as above.
