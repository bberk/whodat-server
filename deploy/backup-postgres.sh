#!/usr/bin/env bash
# Dump the production Postgres container to a gzipped SQL file on the host.
#
#   deploy/backup-postgres.sh
#
# Intended to run as the deploy user from deploy/systemd/whodat-backup.timer, but it is safe to
# run by hand. Each run writes whodat-<UTC timestamp>.sql.gz, then deletes dumps older than
# BACKUP_RETENTION_DAYS. Overrides:
#
#   BACKUP_DIR              destination directory (default /var/backups/whodat)
#   BACKUP_RETENTION_DAYS   days to keep (default 14)
#   COMPOSE_FILE            compose file (default <repo>/deploy/docker-compose.prod.yml)
#   ENV_FILE                compose env file (default <repo>/deploy/.env)
#
# The database user and name come from the running postgres container, so this script does not
# duplicate or hardcode the credentials in deploy/.env.
#
# The dump contains all application data: treat the directory as sensitive. It stays on the VM,
# so copy it off-box as well if you need disaster recovery rather than accidental-deletion
# recovery. Restore steps are in docs/DEPLOY_ORACLE.md.
set -euo pipefail
umask 077

die() {
  echo "backup: $*" >&2
  exit 1
}

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_root/deploy/docker-compose.prod.yml}"
env_file="${ENV_FILE:-$repo_root/deploy/.env}"
backup_dir="${BACKUP_DIR:-/var/backups/whodat}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"

[[ -f "$compose_file" ]] || die "missing $compose_file"
[[ -f "$env_file" ]] || die "missing $env_file"
[[ "$retention_days" =~ ^[0-9]+$ ]] || die "BACKUP_RETENTION_DAYS must be an integer"
command -v docker >/dev/null 2>&1 || die "docker is not installed"

# 0700: only the owner may list or read the dumps.
install -d -m 700 "$backup_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/whodat-$timestamp.sql.gz"
tmp="$target.partial"

cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

# --clean --if-exists makes the dump replayable over an existing database. The container owns
# POSTGRES_USER/POSTGRES_DB, so the dump target always matches the running service.
docker compose -f "$compose_file" --env-file "$env_file" exec -T postgres \
  sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --no-password --clean --if-exists' |
  gzip -9 >"$tmp"

[[ -s "$tmp" ]] || die "the dump is empty"
gzip -t "$tmp" || die "the dump is not valid gzip"
chmod 600 "$tmp"
mv "$tmp" "$target"

find "$backup_dir" -maxdepth 1 -type f -name 'whodat-*.sql.gz' \
  -mtime +"$retention_days" -delete

printf 'backup: wrote %s (%s bytes), retained %s days\n' \
  "$target" "$(wc -c <"$target")" "$retention_days"
