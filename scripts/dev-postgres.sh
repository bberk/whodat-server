#!/usr/bin/env bash
# Start a Postgres 18 instance that belongs to THIS git worktree only.
#
# Tests run on SQLite by default (locally and in the pre-push hook); CI and production use
# Postgres (see AGENTS.md). When you need a real Postgres -- dialect/SQL differences, migrations,
# or a Postgres-only feature -- use this instead of the shared `docker compose up postgres` stack.
#
# Each worktree gets its own Compose project (its own container and data volume) and its own host
# port, both derived from the worktree path, so several agents can run Postgres at the same time
# without colliding with each other or with the default stack on port 5432.
#
# Usage:
#   scripts/dev-postgres.sh up     start it, then print the DATABASE_URL
#   scripts/dev-postgres.sh url    print the DATABASE_URL (does not start anything)
#   scripts/dev-postgres.sh down   stop it and delete this worktree's data
set -euo pipefail

repo="$(git rev-parse --show-toplevel)"
seed="$(printf '%s' "$repo" | cksum | cut -d' ' -f1)"
project="whodat-pg-$seed"
port="$(( 20000 + seed % 40000 ))"
url="postgresql+psycopg://app:app@localhost:$port/app"
compose=(docker compose -p "$project" -f "$repo/docker-compose.yml")

case "${1:-up}" in
  up)
    POSTGRES_PORT="$port" "${compose[@]}" up -d --wait postgres
    cat <<EOF
Postgres for this worktree is up (compose project $project, host port $port).
Point the app, Alembic, or the tests at it with:

  export DATABASE_URL=$url

Then, from backend/:

  uv run alembic upgrade head
  uv run pytest

Stop it and delete this worktree's data with: scripts/dev-postgres.sh down
EOF
    ;;
  url)
    echo "export DATABASE_URL=$url"
    ;;
  down)
    "${compose[@]}" down -v
    ;;
  *)
    echo "usage: scripts/dev-postgres.sh [up|url|down]" >&2
    exit 2
    ;;
esac
