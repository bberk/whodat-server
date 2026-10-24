#!/usr/bin/env bash
# Dump the compose Postgres database, compress it locally, and retain 14 days of dumps.
#
# Laptop (normally called by manage.sh, with DOCKER_CONTEXT already checked):
#   ./backup.sh ./chosen-backup-directory
# Server (from this kit, with its .env and the local Docker context):
#   ./backup.sh ./chosen-backup-directory
# Restore through the laptop wrapper:
#   DOCKER_CONTEXT=whodat-server ./manage.sh restore ./chosen-backup-directory/<dump>.sql.gz
#
# The dump stream crosses SSH to the chosen directory on the machine running this script.
set -euo pipefail

umask 077

fail() {
  printf 'backup.sh: %s\n' "$*" >&2
  exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backup_dir="${1:-${BACKUP_DIR:-$PWD/backups}}"
project_name="${COMPOSE_PROJECT_NAME:-whodat-server}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
filename="whodat-${timestamp}.sql.gz"
destination="${backup_dir%/}/${filename}"
temporary="${destination}.tmp.$$"

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v gzip >/dev/null 2>&1 || fail "gzip is required"
[[ -f "${script_dir}/.env" ]] || fail "copy .env.example to ${script_dir}/.env first"

compose=(
  docker compose
  --project-name "$project_name"
  --project-directory "$script_dir"
  --file "${script_dir}/docker-compose.yml"
  --env-file "${script_dir}/.env"
)

mkdir -p -- "$backup_dir"
[[ -d "$backup_dir" ]] || fail "backup destination is not a directory: $backup_dir"
[[ ! -e "$destination" ]] || fail "backup already exists: $destination"

cleanup() {
  rm -f -- "$temporary"
}
trap cleanup EXIT

# Read the effective user and database inside Postgres; no password appears in this command.
# --clean/--if-exists makes the plain SQL suitable for the managed, transactional restore.
# shellcheck disable=SC2016 # The remote shell expands these variables inside the container.
"${compose[@]}" exec -T postgres sh -c \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
    --format=plain --clean --if-exists --no-owner --no-acl' \
  | gzip -9 >"$temporary"

gzip -t -- "$temporary"
mv -- "$temporary" "$destination"
chmod 600 -- "$destination"

# find rounds file age down to 24-hour units; +13 removes files at least 14 days old.
find "$backup_dir" -type f -name 'whodat-????????T??????Z.sql.gz' -mtime +13 -delete

printf 'Backup written to %s\n' "$destination"
