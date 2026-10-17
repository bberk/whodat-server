# Open questions and deviations

Agents append an entry here (instead of guessing) when a spec document is wrong, missing, or
ambiguous, or when implementation deviates from a document. Each entry records: what was found,
the options, a recommendation, and what was done in the meantime.

Follow the format used below. Newest entries at the top.

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
  `gh pr view --json` payloads: push with and without `AGENT_AUTOSHIP`, refusal on `main`, `--ready`
  (ready + label), draft and closed PRs, no/pending/failing checks, every governance path, and
  `--allow-governance`. Covers AC-WF-07, AC-WF-08, AC-WF-09, AC-WF-13, and AC-WF-15.

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
