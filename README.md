# Victory Points Fantasy Football Standings

A web app that pulls fantasy football league data from ESPN and shows standings ranked by a
custom **Victory Points (VP)** scoring system instead of a plain win/loss record.

## What it does

Each regular-season week, every team earns VP from four components: a head-to-head win (+1),
a top-half score (+1), the highest score of the week (+1), and the lowest score of the week
(-1). Ties split the points exactly (for example, three teams tied for the high score get
1/3 each). The app shows overall standings, per-division standings, a per-week VP table, and a
cumulative VP chart. Members sign up, are linked to their team owner, and see only their
league's data.

ESPN access is isolated behind a provider interface, so other league providers can be added
later without changing the VP engine, database, API, or frontend.

## Status

`0.x` — under active development. See the milestones in `SPEC.md` (section 8). Production
deployment is **not implemented yet**; see [Deploy to production](#deploy-to-production).

## Documentation

- [`SPEC.md`](SPEC.md) — what we are building and the authoritative VP rules.
- [`ACCEPTANCE.md`](ACCEPTANCE.md) — the testable acceptance criteria.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module boundaries, data model, interfaces, API contract.
- [`AGENTS.md`](AGENTS.md) — how agents work in this repository (branch/PR/review workflow).
- [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md) — one-time repository and identity setup.
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — unresolved questions and deviations.

## Tech stack

Python 3.15 + FastAPI + SQLAlchemy/Alembic + Pydantic; SQLite for local dev and tests,
Postgres for production. React + TypeScript + Vite + Tailwind on the frontend. Tooling: `uv`,
`pnpm`, `pytest`, `ruff`, `mypy`, `vitest`, `eslint`, `prettier`, `pre-commit`, GitHub Actions.

## Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python deps and commands | `brew install uv` |
| [pnpm](https://pnpm.io/) | Frontend deps and commands | `brew install pnpm` (or `corepack enable`) |
| Node.js 26 | Frontend runtime | `brew install node@26` |
| [pre-commit](https://pre-commit.com/) | Git hooks | `uv tool install pre-commit` |
| `gh` | PR/merge automation | `brew install gh` then `gh auth login` |
| [gitleaks](https://github.com/gitleaks/gitleaks) | Secret scanning hook | `brew install gitleaks` |
| Docker (optional) | Postgres for local dev | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |

## Setup

```bash
git clone <repo-url> && cd whodat-server

# Backend
cd backend && uv sync && cd ..

# Frontend
cd frontend && pnpm install && cd ..

# Git hooks (commit, push, and post-commit stages)
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type post-commit

# Environment
cp .env.example .env   # then edit values as needed
```

## Run the server locally

Backend API (default `http://localhost:8000`; interactive docs at `/docs`):

```bash
cd backend
uv run uvicorn app.api.main:app --reload
```

Frontend dev server (default `http://localhost:5173`, proxying the API):

```bash
cd frontend
pnpm dev
```

Apply database migrations before first use:

```bash
cd backend
uv run alembic upgrade head
```

To run the backend against Postgres instead of SQLite, start it with Docker and point
`DATABASE_URL` at it:

```bash
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/app uv run alembic upgrade head
```

## Run the tests

```bash
# Backend (tests, lint, types)
cd backend
uv run pytest
uv run pytest --cov=app --cov-branch --cov-report=term-missing   # coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy src

# Frontend (tests, lint, types)
cd frontend
pnpm test
pnpm test:coverage
pnpm lint
pnpm typecheck

# Everything, exactly as CI runs it
pre-commit run --all-files
```

Coverage gates: backend total ≥ 85%, the VP engine (`backend/src/app/domain/`) 100% lines and
branches, and the frontend thresholds in `frontend/vitest.config.ts`.

## Deploy to production

Not implemented yet. When deployment lands, this section will document the target host, the
production `DATABASE_URL`, migration and release steps, and the environment variables required.
Until then there is no supported production deployment.

## Repository layout

```text
backend/     FastAPI app (src/app), migrations (alembic), tests
frontend/    React + TypeScript SPA (src), vitest/eslint config
docs/        GITHUB_SETUP.md, OPEN_QUESTIONS.md, fixtures
scripts/     ship.sh, review.sh, merge.sh, setup-github.sh, coverage_report.py
.github/     CI workflow and pull-request template
```

## Contributing

Human contributors: open a PR against `main` and make sure CI is green.
Agents: read [`AGENTS.md`](AGENTS.md) first — it defines the branch, commit, review, and merge
workflow, the architectural boundaries, and the quality gates.
