# Victory Points Fantasy Football Standings

A web app that pulls fantasy football league data from ESPN and shows standings ranked by a
custom **Victory Points (VP)** scoring system instead of a plain win/loss record.

## What it does

Each regular-season week, every team earns VP from four components: a head-to-head win (+1),
a top-half score (+1), the highest score of the week (+1), and the lowest score of the week
(-1). Ties split the points exactly (for example, three teams tied for the high score get
1/3 each). The app shows overall standings with a VP column for each week, per-division
standings, and a cumulative VP chart. It also shows WAPDate standings: the worst team in each
fixed four-week period (weeks 1-4, 5-8, 9-12), ordered by VP, then wins, then points for, with
teams that are already safe from last place greyed in the current period. Members sign up, are
linked to their team owner, and see only their league's data.

ESPN access is isolated behind a provider interface, so other league providers can be added
later without changing the VP engine, database, API, or frontend.

## Status

`0.x` — under active development. See the milestones in `SPEC.md` (section 8). A single-host
Docker Compose stack exists, and production deployment to one Oracle Cloud Always Free ARM VM is
documented in [`docs/DEPLOY_ORACLE.md`](docs/DEPLOY_ORACLE.md); see
[Deploy to production](#deploy-to-production).

## Documentation

- [`SPEC.md`](SPEC.md) — what we are building and the authoritative VP rules.
- [`ACCEPTANCE.md`](ACCEPTANCE.md) — the testable acceptance criteria.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module boundaries, data model, interfaces, API contract.
- [`AGENTS.md`](AGENTS.md) — how agents work in this repository (branch/PR/review workflow).
- [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md) — one-time repository and identity setup.
- [`docs/DEPLOY_ORACLE.md`](docs/DEPLOY_ORACLE.md) — production runbook for the Oracle Cloud VM.
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — unresolved questions and deviations.

## Tech stack

Python 3.15 + FastAPI + SQLAlchemy/Alembic + Pydantic; SQLite for local dev,
Postgres in CI and production. React + TypeScript + Vite + Tailwind on the frontend. Tooling: `uv`,
`pnpm`, `pytest`, `ruff`, `mypy`, `vitest`, `eslint`, `prettier`, `pre-commit`, GitHub Actions.

## Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python deps and commands | `brew install uv` |
| [pnpm](https://pnpm.io/) | Frontend deps and commands | `brew install pnpm` (or `corepack enable`) |
| Node.js 26.12.1 or newer | Frontend runtime | `brew install node@26` |
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

# Git hooks (commit and push stages)
pre-commit install --hook-type pre-commit --hook-type pre-push

# Environment
cp .env.example .env   # then edit values as needed
```

`.env` is read by both the host backend and Compose: the backend loads it for a host-run process,
and Compose reads the repo-root file for variable substitution before starting containers. Leaving
`DATABASE_URL` unset (the `.env.example` default) lets the Compose backend use its `postgres`
service; setting `DATABASE_URL` overrides that for the containers too. `CORS_ORIGINS` must include
every frontend origin you use: `http://localhost:5173` for the Vite dev server and
`http://localhost:8080` for the Compose frontend.

If your `.env` came from an older example, add `http://localhost:8080` to `CORS_ORIGINS` and unset
`DATABASE_URL` (or point it at the Compose Postgres service) before recreating the stack.

ESPN credentials are **not** environment variables. Each member enters the league's `ESPN_S2`
and `ESPN_SWID` cookies for that membership in the UI; they are stored encrypted per membership
(under `LEAGUE_CREDENTIALS_KEY`) and never logged or returned by the API.

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

Or run the whole stack in Docker, with the built frontend on `http://localhost:8080`:

```bash
docker compose up -d --build
```

Compose reads the same repo-root `.env` for substitution. With `DATABASE_URL` unset the backend
uses the compose `postgres` service; `CORS_ORIGINS` must include `http://localhost:8080` for the
composed frontend.

Apply database migrations before first use:

```bash
cd backend
uv run alembic upgrade head
```

To run the backend against Postgres instead of SQLite, start a Postgres that belongs to **this
worktree** and point `DATABASE_URL` at it:

```bash
scripts/dev-postgres.sh up    # starts it and prints the exact `export DATABASE_URL=...` line
# paste that export, then:
cd backend
uv run alembic upgrade head
```

`scripts/dev-postgres.sh` gives each git worktree its own container, data volume, and host port, so
several checkouts can run Postgres at once without clobbering each other. `scripts/dev-postgres.sh
down` stops it and deletes this worktree's data. The plain `docker compose up -d postgres` stack
(port 5432) is fine for a single checkout.

## First run: accounts and leagues

There are no seeded users and no self-service signup: every account is created by redeeming an
invite code at `/signup`. Create the first (admin) invite on the host:

```bash
cd backend
uv run python -m app.cli create-invite --role admin
```

The command prints the raw code once — save it now; only its hash is stored and the code cannot be
shown again. Invites expire after 7 days by default; pass `--expires 24h` (or another `Nd`/`Nh`
duration, up to 3650 days) to change that.

When the stack runs in Docker, run the same command inside the backend container:

```bash
docker compose exec backend uv run python -m app.cli create-invite --role admin
```

Sign up at `http://localhost:5173/signup` for the dev servers, or
`http://localhost:8080/signup` for the Docker stack. An admin invite is league-less, so signup
then forces the **create your league** step: enter the ESPN league id, season, `ESPN_S2`, and
`ESPN_SWID`. Standings stay unreachable until that step succeeds.

To invite a member, create a member invite bound to the league's ESPN id (an admin must have
stored that league first):

```bash
cd backend
uv run python -m app.cli create-invite --role member --league <espn-league-id>
```

A member invite is bound to exactly one league, so the new account lands directly in that league at
signup. An existing member joins an additional league from the UI's **Join league** action with a
member invite code; joining is never done by typing a bare league id. Admins need no invite: they
add any league from the UI with its ESPN id and credentials.

`create-invite` enforces the role/league pairing: `--role member` requires `--league`, and
`--role admin` rejects it.

Credentials are per membership. Members enter the league's `ESPN_S2` and `ESPN_SWID` in the UI;
they are stored encrypted under `LEAGUE_CREDENTIALS_KEY` and never returned by the API. The admin
page's **Seasons** table is the only refresh control: each row refreshes one season with the
caller's own stored credentials. Refresh is rate limited (one league-wide refresh every five
minutes, and three per user per hour), and changing a cup week recomputes standings without
contacting ESPN.

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

# End-to-end (Playwright at 360, 768, and 1280; migrates, seeds, and starts both servers)
pnpm e2e:install   # once per machine
pnpm e2e

# Everything, exactly as CI runs it
pre-commit run --all-files
```

The e2e suite uses `e2e/seed.py` and `e2e/fixture.json` to build a deterministic league through
the real services and the `FakeProvider`. It never calls ESPN and talks only to the local API and
frontend servers.

Coverage gates: backend total ≥ 85%, the VP engine (`backend/src/app/domain/`) 100% lines and
branches, and the frontend thresholds in `frontend/vitest.config.ts`.

## Deploy to production

Production runs on a single Oracle Cloud Always Free ARM VM with Docker Compose. Caddy is the only
ingress (ports 80/443) and terminates TLS; it proxies `/api/*` and `/health` to the backend and
everything else to the frontend, so the SPA and API share one origin and the `SameSite=Lax`
session cookie works unchanged. Postgres keeps its data in a named volume, and GitHub Actions
deploys only after CI passes on `main`.

The full runbook — VM and firewall setup, DNS, secrets, first deploy, creating the first admin
invite, GitHub environment configuration, rollback, nightly backups and restore, and caveats — is
[`docs/DEPLOY_ORACLE.md`](docs/DEPLOY_ORACLE.md).

Local development still uses the root `docker-compose.yml`:

```bash
docker compose up -d --build      # frontend on :8080, API on :8000, Postgres on :5432
docker compose up -d postgres     # just the database for a host-run backend
```

The production stack is a separate compose file rather than an override of the local one, so the
two never depend on merge semantics:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
```

Both stacks build the same two images:

- `backend/Dockerfile` installs from `uv.lock` and runs `alembic upgrade head` before uvicorn.
- `frontend/Dockerfile` builds the SPA with pnpm and serves it with nginx. The API origin is
  compiled into the bundle, so `VITE_API_BASE_URL` must be set before building and the frontend
  must be rebuilt whenever it changes; `deploy/deploy.sh` always rebuilds.

The production values live in `deploy/.env` (copied from `deploy/.env.example`); never commit real
values. It defines:

| Variable | Purpose |
|---|---|
| `ENV` | Deployment label; set `production`. The app refuses to start with the default secret when `ENV` is not `local` or `test`. |
| `SECRET_KEY` | Signs session cookies. Required; generate with `openssl rand -hex 32`. |
| `LEAGUE_CREDENTIALS_KEY` | Encrypts stored league credentials (base64-encoded 32 bytes). Required when members save ESPN credentials; generate with `openssl rand -base64 32`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Production database identity. The local-dev `app`/`app` pair is never used; generate the password with `openssl rand -hex 32`. |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to send the session cookie, for example `https://standings.example.com`. |

`deploy/docker-compose.prod.yml` builds the backend's `DATABASE_URL` from those Postgres values,
so it always points at `postgres:5432` with the same database and password. The password must stay
hex so the URL needs no encoding.

`VITE_API_BASE_URL` is a frontend build arg, set to `https://$DOMAIN` by the production compose
file. ESPN cookies are entered per league in the UI and stored encrypted on the membership; there
is no environment `ESPN_S2`/`ESPN_SWID` setting to deploy.

Migrations are applied by the backend container on startup, so a deploy is idempotent. To run them
separately against the production database first:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  run --rm backend uv run alembic upgrade head
```

Check the deployed stack from the VM or anywhere:

```bash
curl -fsS "https://$DOMAIN/health"    # {"status":"ok"}
```

Caveats of this target — one node with no HA, Oracle reclaiming idle Always Free instances, ARM
capacity at signup, backups that share the VM's disk, and patching — are documented in the
runbook before you rely on it.

Local development is unchanged: `docker compose up -d postgres` still starts just the database for
a host-run backend.

## Repository layout

```text
backend/     FastAPI app (src/app), migrations (alembic), tests
frontend/    React + TypeScript SPA (src), vitest/eslint config, Playwright specs
e2e/         deterministic e2e seeder, shared fixture, and backend start script
deploy/      production Compose stack, Caddyfile, deploy/backup scripts, systemd units
.opencode/   Author and reviewer agent instructions
docs/        GITHUB_SETUP.md, DEPLOY_ORACLE.md, OPEN_QUESTIONS.md, fixtures
scripts/     ship.sh, cleanup.sh, review.sh, merge.sh, setup-github.sh, dev-postgres.sh,
             coverage_report.py
.github/     CI and deploy workflows, pull-request template
```

## Contributing

Human contributors: open a PR against `main` and make sure CI is green.
Agents: read [`AGENTS.md`](AGENTS.md) first — it defines the branch, commit, review, and merge
workflow, the architectural boundaries, and the quality gates.
