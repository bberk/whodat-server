#!/usr/bin/env bash
# Backend for the Playwright suite: migrate, seed, then serve with uvicorn.
#
# DATABASE_URL and CORS_ORIGINS may be set by the caller (CI uses its Postgres service). Locally
# they default to a worktree-local SQLite file and the Vite preview origin.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

cd "$root/backend"
export PYTHONPATH="$root/backend/src${PYTHONPATH:+:$PYTHONPATH}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$root/e2e/e2e.db}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:4173,http://127.0.0.1:4173}"

uv run alembic upgrade head
uv run python "$here/seed.py"
exec uv run uvicorn app.api.main:app --host 127.0.0.1 --port "${E2E_API_PORT:-8000}"
