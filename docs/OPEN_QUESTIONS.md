# Open questions and deviations

Agents append an entry here (instead of guessing) when a spec document is wrong, missing, or
ambiguous, or when implementation deviates from a document. Each entry records: what was found,
the options, a recommendation, and what was done in the meantime.

Follow the format used below. Newest entries at the top.

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
