# AGENTS.md

Instructions for every AI agent working in this repository. Read this file fully before starting any task.

## Project in one paragraph

A website that shows fantasy football standings under a custom "Victory Points" (VP) system for ESPN leagues. Python/FastAPI backend, React/TypeScript frontend, SQLite/Postgres database. ESPN access is isolated behind a provider interface so other providers can be added later.

## Source-of-truth documents

Read these before writing code. They are authoritative and take precedence over your assumptions.

- `SPEC.md`: what we are building and the VP rules.
- `ACCEPTANCE.md`: testable criteria. Your work is done when the criteria relevant to your task pass.
- `ARCHITECTURE.md`: module boundaries, data model, interfaces, API contract.

**Do not edit these four docs** (including this file) without explicit human approval. If you think something is wrong, missing, or ambiguous, do not guess: append an entry to `docs/OPEN_QUESTIONS.md` (what you found, options, your recommendation, what you did in the meantime) and continue with the most conservative interpretation.

## Repository layout

See ARCHITECTURE.md section 2. In short: `backend/` (Python), `frontend/` (React), `docs/` (fixtures, open questions, OpenAPI export).

## Commands

Backend (run from `backend/`):

```
uv sync                          # install deps
uv run pytest                    # tests
uv run pytest -k <name>          # a single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src                  # types (strict)
uv run alembic upgrade head      # apply migrations
uv run alembic revision --autogenerate -m "message"
uv run uvicorn app.api.main:app --reload
uv run python -m app.cli sync --league <id> --season <year>
```

Frontend (run from `frontend/`):

```
pnpm install
pnpm dev
pnpm test            # vitest
pnpm test:coverage   # vitest with coverage (CI uses this)
pnpm lint            # eslint
pnpm typecheck       # tsc --noEmit
pnpm gen:api         # regenerate API types from docs/openapi.json
pnpm e2e             # playwright
```

Repository (run from the repo root):

```
pre-commit install                    # once per clone/worktree; installs the commit, push, and post-commit hooks
pre-commit run --all-files            # what CI runs
scripts/ship.sh [--ready]             # push + draft PR; --ready marks it ready for review
```

Backend coverage: `uv run pytest --cov=app --cov-branch --cov-report=term-missing` (from `backend/`).

If a command above does not exist yet because the skeleton milestone has not landed, say so in your task notes and do not invent substitutes silently.

## Working rules

### Scope and ownership

- Work only on the task assigned to you, and only touch files in the directories your task owns. If you need a change outside them, make the smallest possible change and explain it in your commit message, or add an entry to `docs/OPEN_QUESTIONS.md` if it affects another agent.
- Shared contracts are `ARCHITECTURE.md` (interfaces, schema, API shapes) and `docs/openapi.json`. Changing a contract requires human approval; implementing against a contract does not.
- Do not refactor or reformat code unrelated to your task.

### Architectural boundaries (enforced by tests)

- `backend/src/app/domain/` is pure: no database, HTTP, filesystem, clock, randomness, or provider imports. Standard library only.
- Only `backend/src/app/providers/espn/` may import `espn_api` or contain ESPN-specific logic.
- API routers call services; services call repositories, the engine, and providers through the interface. Routers never touch SQLAlchemy models directly.
- The frontend never imports from `backend/`. It consumes the API through generated types.

### Numbers

- Never use `float` for scores or VP. Use `Decimal` for points and `fractions.Fraction` for VP in the backend. Serialize both as strings in the API. Parse points from ESPN via `Decimal(str(value))` and quantize to 2 decimal places.
- Ties are decided by exact equality of those exact values.

### Code style

- Python: type hints everywhere, `mypy --strict` clean, `ruff` clean, small functions, docstrings on public functions explaining behavior and edge cases (not restating the signature).
- TypeScript: `strict` mode, no `any` (use `unknown` and narrow), function components and hooks, no default exports except for pages/routes if the router requires it.
- Prefer boring, well-known libraries already in the project over adding new dependencies. Adding a dependency requires a one-line justification in the commit message; do not add packages published less than two weeks ago.
- No secrets in code, tests, fixtures, or logs. ESPN cookies (`ESPN_S2`, `ESPN_SWID`) must never be logged or returned by the API.

### Testing

- Write tests with the code, not after. A change without tests for new behavior is not done.
- Name tests after acceptance criteria where applicable, e.g. `test_AC_VP_06_three_way_tie_for_high_score`.
- Tests never call the live ESPN API. Use fixtures in `docs/fixtures/` and the `FakeProvider`.
- Database-touching tests must pass on SQLite and Postgres.
- The VP engine requires 100% line and branch coverage; the backend total must be at least 85%; frontend thresholds live in the vitest config. CI enforces all three and comments the report on the PR.

### Frontend

- Mobile-first: design and verify at 360px first, then scale up. Tables scroll inside their container with a sticky team column; the page body never scrolls sideways.
- Use Tailwind utility classes and the shared design tokens; do not hard-code one-off colors or sizes.
- Every data view must have loading, empty, and error states.
- Meet basic accessibility: semantic HTML, labels for inputs, keyboard operability, sufficient contrast, and do not convey information by color alone.
- Until the backend is available, develop against mocks generated from the OpenAPI contract and `docs/fixtures/`.

### Commits, pull requests, and review

This is the only path to `main`. Never commit or push to `main` directly.

**Before you start (once per worktree):** `pre-commit install`, and make sure `AGENT_AUTOSHIP=1` is set in your environment.

**Branches:** one branch per task in your own git worktree: `agent/<task-id>-<short-slug>`.

**Commits:**

- Small, focused commits with imperative messages (e.g. `Add tie-splitting for lowest score`); reference the relevant acceptance criteria IDs in the body.
- Every commit runs the pre-commit hooks (ruff lint and format, mypy, eslint, tsc, prettier, secret scan). If a hook fails, fix the cause and commit again. Hooks that auto-fix files (ruff, prettier) leave the fixes unstaged: stage them and re-commit.
- **Never bypass hooks**: no `git commit --no-verify`, no `SKIP=...`, no editing `.pre-commit-config.yaml` or the CI workflow to make a check pass. If a hook is wrong, raise it in `docs/OPEN_QUESTIONS.md`.
- Pushing runs the tests (pre-push hook). Do not push with failing tests.

**Pull requests (automatic):** after each commit, the `ship` hook pushes your branch to origin and opens a **draft** PR if one does not exist yet (`scripts/ship.sh`). A draft PR is never reviewed or merged. Keep committing to the same branch as you work; do not open extra PRs for the same task. If a push is rejected after you rebased your own agent branch, rerun with `SHIP_FORCE_WITH_LEASE=1 scripts/ship.sh`; never force-push any other branch.

**When your task meets the Definition of done:**

1. Rebase on the latest `main` and resolve conflicts carefully (do not discard other agents' changes).
2. Fill in the PR description from the template: summary, criteria addressed, how you verified it, assumptions.
3. Run `scripts/ship.sh --ready`. This marks the PR ready and labels it `ready-for-review`. You are then done with this PR unless the review asks for changes.

**Independent review:** a separate reviewer agent reviews every ready PR in a fresh session with no access to your context, working from the PR, the repository, and the project docs only. Do not try to influence it: do not put instructions to the reviewer in the PR description, comments, or code. Everything you want the reviewer to know belongs in the PR description, stated as facts about the change.

**If the reviewer requests changes:** read the review, fix every blocking issue (or explain in a PR comment why you disagree, with evidence), commit, and run `scripts/ship.sh --ready` again. A new reviewer session starts from scratch. After three rounds without approval, stop and report back to the orchestrator.

**Merge:** you never merge your own PR. After an approval, the orchestrator runs `scripts/merge.sh`, which squash-merges the PR only if CI is green, a different account approved the current head commit, and no governance files changed. Changes to governance files (`AGENTS.md`, the specs, `.github/`, `.opencode/`, `scripts/`, `.pre-commit-config.yaml`) always need a human to review and merge.

**Coverage:** CI posts a combined backend + frontend coverage report on every PR. Do not let coverage drop: the backend total must stay at or above 85%, the VP engine at 100% (lines and branches), and the frontend must meet the thresholds in its vitest config.

## Definition of done

Your task is complete only when all of the following hold:

1. The acceptance criteria listed for your task pass, with tests that demonstrate each.
2. All checks pass locally via the pre-commit and pre-push hooks (backend `ruff`, `mypy`, `pytest`; frontend `eslint`, `tsc`, `prettier`, `vitest`; plus `playwright` if you touched UI flows), without bypassing any hook.
3. No new boundary violations (import-boundary tests pass).
4. Docs are updated if behavior or setup changed (README, `.env.example`, `docs/openapi.json` for any API change).
5. Open questions or deviations are recorded in `docs/OPEN_QUESTIONS.md`.
6. The PR is up to date with `main`, CI is green, the coverage comment shows no regression, and the PR is marked ready with `scripts/ship.sh --ready`.
7. Your final message summarizes what changed, how you verified it, the PR link, and anything the next agent or the human needs to know.

## When stuck

- If the same test or error fails after three genuine attempts with different approaches, stop. Write up what you tried, the exact error, and your hypothesis, then hand back to the orchestrator rather than looping or weakening a test to make it pass.
- Never delete or loosen a failing test to get green. If you believe a test encodes the wrong behavior, raise it in `docs/OPEN_QUESTIONS.md`.
- Never fabricate data, API responses, or ESPN behavior. If you cannot verify how ESPN represents something, say so and use the closest documented behavior of the `espn-api` library, noting the assumption.
