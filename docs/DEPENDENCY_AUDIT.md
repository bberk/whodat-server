# Dependency audit — 2026-10-25

Scope: every external dependency in `backend/`, `frontend/`, the Dockerfiles and Compose stacks,
GitHub Actions, pre-commit hooks, and the pinned runtime/tooling versions. No application feature
changed; the only source edits are compatibility fixes required by the upgrades and two
accessibility-name corrections found by axe.

Latest-version sources (queried on 2026-10-25):

- PyPI JSON API (`https://pypi.org/pypi/<name>/json`).
- npm registry (`https://registry.npmjs.org/<name>/latest`).
- Docker Hub tags API (`https://hub.docker.com/v2/repositories/library/<image>/tags`).
- GitHub Releases API (`https://api.github.com/repos/<owner>/<repo>/releases/latest`).
- Upstream release pages: `python.org`, `nodejs.org/dist/index.json`, `nginx.org/en/download.html`.

Only stable releases were considered. Postgres 19 (`19rc1`) and any other release candidate were
excluded.

## Runtime floors and tooling

| Item | Before | After | Notes |
| --- | --- | --- | --- |
| Python floor (`requires-python`) | 3.15 | 3.15 | 3.15.1 is the current image; 3.15.2 sources were published 2026-10-25 but no 3.15.2 Docker tag existed at audit time. The rolling `3.15-alpine` tag will pick it up. |
| Node engine | 26.12.1 | 26.12.1 | Already the newest stable release. |
| pnpm | 12.14.0 | 12.15.0 | Latest stable; also in `packageManager` and the frontend image. |
| uv | 0.8.8 | 0.13.5 | Latest stable; musl variant used by the Alpine backend image. |
| gitleaks | 8.30.1 | 8.30.1 | Already the latest release. |

## Backend Python

Direct dependencies, resolved before → after:

| Package | Before | After |
| --- | --- | --- |
| fastapi | 0.143.3 | 0.162.0 |
| uvicorn[standard] | 0.54.0 | 0.54.0 |
| sqlalchemy | 2.1.5 | 2.1.6 |
| alembic | 1.20.0 | 1.20.1 |
| pydantic | 2.14.1 | 2.14.1 |
| pydantic-settings | 2.16.0 | 2.16.1 |
| psycopg[binary] | 3.3.6 | 3.3.6 |
| espn-api | 1.0.1 | 1.0.1 |
| cryptography | 50.0.2 | 50.0.2 |
| argon2-cffi | 25.1.0 | 25.1.0 |
| hypothesis (dev) | 6.122.7 | 6.170.11 |
| httpx (dev) | 0.28.1 | 0.28.1 |
| mypy (dev) | 2.4.0 | 2.4.0 |
| pytest (dev) | 9.1.1 | 9.1.1 |
| pytest-cov (dev) | 7.1.0 | 7.1.0 |
| ruff (dev) | 0.17.1 | 0.17.2 |

`uv lock --upgrade` also moved these transitive packages: `starlette` 1.8.0 → 1.10.0, `certifi`
2026.7.22 → 2026.10.23, `coverage` 7.16.2 → 7.17.0, `websockets` 17.2 → 17.3, and `pycparser`
3.0 → 3.12. `attrs` is no longer required.

Minimum constraints in `backend/pyproject.toml` were raised to the verified resolutions so a
future install cannot silently downgrade below the audited set. The narrow `hypothesis<6.123`
upper bound was removed.

`idna` stays at 3.15 even though 3.20 is the latest release: `espn-api==1.0.1` declares
`idna>=3.15,<3.16`, so 3.20 makes the graph unsatisfiable. This is recorded under deferred items.

## Frontend npm

Direct dependencies, resolved before → after:

| Package | Before | After |
| --- | --- | --- |
| react | 18.3.1 | 19.3.1 |
| react-dom | 18.3.1 | 19.3.1 |
| react-router-dom | 7.18.4 | 7.18.4 |
| @axe-core/playwright | 4.13.0 | 4.14.0 |
| @eslint/js | 9.39.5 | 10.0.1 |
| @playwright/test | 1.63.0 | 1.64.1 |
| @tailwindcss/postcss | — | 4.3.3 |
| @testing-library/jest-dom | 6.9.1 | 7.0.1 |
| @testing-library/react | 16.3.3 | 16.3.3 |
| @testing-library/user-event | 14.6.8 | 14.6.8 |
| @types/node | 26.6.3 | 26.6.5 |
| @types/react | 18.3.31 | 19.3.0 |
| @types/react-dom | 18.3.7 | 19.3.0 |
| @vitejs/plugin-react | 4.7.0 | 6.1.2 |
| @vitest/coverage-v8 | 5.0.5 | 5.0.5 |
| autoprefixer | 10.6.1 | removed |
| eslint | 9.39.5 | 10.13.0 |
| eslint-plugin-react-hooks | 5.2.0 | 7.1.1 |
| eslint-plugin-react-refresh | 0.4.26 | 0.5.7 |
| globals | 15.15.0 | 17.13.0 |
| jsdom | 25.0.1 | 30.1.3 |
| openapi-typescript | 7.13.0 | 7.13.0 |
| postcss | 8.5.30 | 8.5.31 |
| prettier | 3.9.10 | 3.9.10 |
| tailwindcss | 3.4.19 | 4.3.3 |
| typescript | 5.9.3 | 5.9.3 |
| typescript-eslint | 8.71.2 | 8.72.0 |
| vite | 6.4.4 | 8.3.5 |
| vitest | 5.0.5 | 5.0.5 |

Tailwind 4 handles vendor prefixing itself, so `autoprefixer` was removed. The dead
`postcss-selector-parser` override and the obsolete `esbuild` build allowance were removed from
`pnpm-workspace.yaml`; neither package is in the Vite 8 / Tailwind 4 tree.

Major migrations that landed: React 19, Vite 8 (`@vitejs/plugin-react` 6), Tailwind 4,
ESLint 10, jsdom 30, and Testing Library jest-dom 7. Vitest was already on the latest major.

Compatibility changes made:

- Tailwind 4: `src/index.css` now uses `@import "tailwindcss"` plus `@config` for the legacy
  token config; `postcss.config.js` uses `@tailwindcss/postcss`; the single `shadow-sm` utility
  became `shadow-xs` to preserve the old shadow size.
- `eslint-plugin-react-refresh` 0.5 no longer treats an object literal as a constant export, so
  `CLINCH_LABELS` is allowed by name in `eslint.config.js`.
- jsdom 30 / Testing Library 16.3 no longer insert a space between adjacent inline spans when
  computing an accessible name. The VP and Elo legend buttons now contain an explicit space, and
  the week sort buttons include their visible `W1` text in the accessible name. This also fixed
  real `label-content-name-mismatch` axe findings.
- One admin-route test now waits for the league switcher to finish loading instead of racing the
  fetch (React 19 resolves the heading earlier).

## Docker images

| Image | Before | After | Notes |
| --- | --- | --- | --- |
| Backend runtime | `python:3.15-slim` | `python:3.15-alpine` | Alpine 3.24 had 0 base OS findings; Debian 13.7 had 44 unfixed high findings. |
| uv in backend image | `ghcr.io/astral-sh/uv:0.8.8` | `ghcr.io/astral-sh/uv:0.13.5-alpine` | Musl build matches the Alpine runtime. |
| Frontend build | `node:26.12.1-alpine` | `node:26.12.1-alpine` | Already latest stable. |
| pnpm in frontend image | `12.14.0` | `12.15.0` | Matches `packageManager`. |
| Frontend runtime | `nginx:1.27-alpine` | `nginx:1.30-alpine-slim` | 1.30.6 is the stable branch; 1.27 is EOL. Slim variant had 0 critical/high findings and keeps BusyBox `wget` for the healthcheck. |
| Compose/CI Postgres | `postgres:18` / `18-alpine` | unchanged | Rolling tags resolve to 18.6; 19 is only an RC. |
| Caddy | `2.10.2` | `2.11.7` | Latest stable. |
| DuckDNS plugin | `v0.5.0` | `v0.5.0` | Already latest. |
| gitleaks | `8.30.1` | `8.30.1` | Already latest. |

The backend image had no `.dockerignore`, so `COPY . .` shipped the host `.venv` and its stale
packages into the image. A backend `.dockerignore` now excludes host virtualenvs, caches, tests,
databases, and env files; the image also removes pip (and its vendored `urllib3`/`msgpack`) after
installing runtime dependencies, and deletes the uv cache. The frontend `.dockerignore` also
excludes Playwright reports now.

The Caddy build pins `golang.org/x/net@v0.60.0` via `xcaddy --replace`, upgrades Alpine packages
at build time (brotli and curl fixes), and is built with the Go 1.27.3 toolchain from the builder
image. `apk upgrade` also picks up the patched Alpine packages without waiting for a new base tag.

## GitHub Actions and pre-commit

| Item | Before | After |
| --- | --- | --- |
| `astral-sh/setup-uv` | v10.3.0 | v10.3.2 |
| `actions/checkout` | v7 | v7 (latest major) |
| `actions/setup-node` | v7 | v7 (latest major) |
| `pnpm/action-setup` | v6 | v6 (latest major) |
| `actions/upload-artifact` | v7 | v7 (latest major) |
| `actions/download-artifact` | v8 | v8 (latest major) |
| `actions/github-script` | v9 | v9 (latest major) |
| `pre-commit/pre-commit-hooks` | v5.0.0 | v6.0.0 |
| `astral-sh/ruff-pre-commit` | v0.17.1 | v0.17.2 |
| gitleaks (CI download) | 8.30.1 | 8.30.1 |

Pre-commit itself is installed in CI with `uv tool install pre-commit` (latest at run time) and is
not pinned in the repository.

## Vulnerability audits

### Application dependency audits

| Audit | Before | After |
| --- | --- | --- |
| `pnpm audit` | 0 advisories | 0 advisories |
| `pip-audit` (locked backend environment) | 1: `certifi` 2026.7.22, PYSEC-2026-4320, fix 2026.10.19 | 0 advisories |

`pip-audit` skips the local `whodat-backend` project because it is not published on PyPI. That is
expected and not an advisory.

### Container scans (Trivy, CRITICAL + HIGH)

| Image | Before | After |
| --- | --- | --- |
| `whodat-backend` | 4 high from pip's vendored `urllib3`/`msgpack`, plus 44 Debian OS findings | 0 |
| `whodat-frontend` | 1 critical + 2 high (nginx 1.27 Alpine packages) | 0 |
| `whodat-caddy` | 4 critical + 14 high (Go stdlib/x/net and Alpine packages) | 0 |

Docker Scout was also run. On the Caddy image it continues to report the base image's published
SBOM (`stdlib 1.26.8`, `x/net 0.59.0`) even after the binary is replaced. A filesystem scan and
`go version -m` show the shipped binary is built with Go 1.27.3 and resolves
`golang.org/x/net v0.59.0 => v0.60.0`; Trivy reports 0. The Scout result is a stale-SBOM artefact,
not a shipped package.

Accepted unpatched advisories: none in the application dependency graphs or final images. The
Debian-only OS findings disappeared by moving to Alpine; no advisory was suppressed.

## Deferred upgrades

| Item | Current | Latest | Blocker / follow-up |
| --- | --- | --- | --- |
| TypeScript | 5.9.3 | 7.0.2 | `typescript-eslint@8.72.0` declares `typescript >=4.8.4 <6.1.0`, so TS 7 breaks lint/type-aware rules. Revisit when typescript-eslint supports TS 7. |
| idna | 3.15 | 3.20 | `espn-api==1.0.1` pins `idna>=3.15,<3.16`; `uv` cannot resolve 3.20. Revisit when espn-api widens the range. No advisory affects 3.15. |
| Postgres | 18.6 | 19rc1 | 19 is a release candidate, not stable. Stay on 18 until 19.0 ships. |
| Python image patch | 3.15.1 | 3.15.2 | Sources were published 2026-10-25, but Docker Hub had no `3.15.2` tag. The rolling `3.15-alpine` tag will move automatically. |

## Verification performed

- Backend: `ruff check`, `ruff format --check`, `mypy src`, and the full `pytest` suite against
  Postgres 18 (1079 passed after rebasing on main; 99.23% coverage; `alembic upgrade head` and
  `alembic check` clean).
- Frontend: `eslint`, `tsc --noEmit` (app and e2e configs), `vitest run --coverage` (345 passed
  after rebasing on main; 96.25% statements, 91.66% branches, 98.17% functions, 96.16% lines —
  above the pre-change baseline), and `vite build`.
- Playwright: 18 tests passed across 360/768/1280 px in light and dark themes, including axe.
- Docker: backend, frontend, and Caddy images all build; backend container applies migrations and
  answers `/health`; both Compose files pass `docker compose config`.
- `pre-commit run --all-files` and the pre-push hooks pass.
