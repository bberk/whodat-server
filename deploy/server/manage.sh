#!/usr/bin/env bash
# Laptop-side management for the remote stack. Set DOCKER_CONTEXT before every remote command.
# Compose files and build contexts are read on this laptop; containers and named volumes are
# remote. No laptop path is mounted into the stack. Backup/restore streams are the exception:
# their local filenames belong to this laptop, never to container volume configuration.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_name="${COMPOSE_PROJECT_NAME:-whodat-server}"
health_timeout="${HEALTH_TIMEOUT:-300}"

usage() {
  cat <<'EOF'
Usage: ./manage.sh <command> [arguments]

Context setup and selection (on the laptop):
  context-create <user@host> [name]  Create an SSH Docker context (default: whodat-server)
  contexts                           List contexts available for selection
  export DOCKER_CONTEXT=<name>       Select the remote context for this shell
  check                              Validate the selection and remote daemon connection

Stack commands (require DOCKER_CONTEXT and deploy/server/.env):
  deploy                             Build images, start the stack, and wait for health
  up                                 Start the stack without rebuilding
  down                               Stop and remove containers; KEEP named volumes
  logs [service ...]                 Follow logs (all services by default)
  ps                                 Show containers and health
  migrate                            Run Alembic migrations in a one-off backend
  shell [service]                    Open a shell (default: backend)
  backup [directory]                 Stream a dump to a laptop directory (default: ./backups)
  restore <file.sql.gz>              Restore a dump after confirmation, then restart the stack
  update                             Pull Postgres, rebuild all images, and start the stack

DOCKER_CONTEXT must name an existing ssh:// context. The default/local Docker daemon is
refused. Compose project files and build contexts remain on the laptop; paths and named
volumes inside containers always resolve on the remote server.
EOF
}

fail() {
  printf 'manage.sh: %s\n' "$*" >&2
  exit 1
}

require_context() {
  local context_name="${DOCKER_CONTEXT:-}"
  local endpoint

  [[ -n "$context_name" ]] ||
    fail "set DOCKER_CONTEXT first (for example: export DOCKER_CONTEXT=whodat-server)"
  command -v docker >/dev/null 2>&1 || fail "docker is required"
  endpoint="$(docker context inspect "$context_name" --format '{{.Endpoints.docker.Host}}' \
    2>/dev/null)" || fail "Docker context does not exist: $context_name"
  case "$endpoint" in
    ssh://*) ;;
    *)
      fail "context '$context_name' is not a remote SSH context (endpoint: ${endpoint:-unknown})"
      ;;
  esac

  export DOCKER_CONTEXT="$context_name"
  docker version --format '{{.Server.Version}}' >/dev/null 2>&1 ||
    fail "cannot reach the remote daemon through context '$context_name'; check SSH and Docker"
}

require_env() {
  [[ -f "${script_dir}/.env" ]] ||
    fail "copy deploy/server/.env.example to deploy/server/.env and replace its placeholders"
}

compose() {
  docker compose \
    --project-name "$project_name" \
    --project-directory "$script_dir" \
    --file "${script_dir}/docker-compose.yml" \
    --env-file "${script_dir}/.env" \
    "$@"
}

remote_note() {
  printf 'manage.sh: remote context %s; containers/volumes are remote, no laptop mounts.\n' \
    "$DOCKER_CONTEXT" >&2
}

wait_for_health() {
  local services=("$@")
  local deadline pending service container_id status

  [[ "$health_timeout" =~ ^[1-9][0-9]*$ ]] || fail "HEALTH_TIMEOUT must be a positive integer"
  if [[ $# -eq 0 ]]; then
    services=(postgres backend frontend caddy)
  fi
  deadline=$((SECONDS + health_timeout))

  while ((SECONDS < deadline)); do
    pending=0
    for service in "${services[@]}"; do
      container_id="$(compose ps --quiet "$service")"
      if [[ -z "$container_id" ]]; then
        pending=1
        continue
      fi
      status="$(docker inspect --format \
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container_id" 2>/dev/null || printf 'missing')"
      case "$status" in
        healthy) ;;
        unhealthy | exited | dead | missing)
          compose ps
          compose logs --tail=100 "$service"
          fail "service '$service' is $status"
          ;;
        *) pending=1 ;;
      esac
    done
    if ((pending == 0)); then
      compose ps
      return 0
    fi
    sleep 5
  done

  compose ps
  compose logs --tail=100
  fail "timed out after ${health_timeout}s waiting for healthy services"
}

create_context() {
  local ssh_target="${1:-}"
  local context_name="${2:-whodat-server}"

  [[ -n "$ssh_target" ]] || fail "usage: manage.sh context-create <user@host> [name]"
  [[ "$ssh_target" != *"://"* ]] || fail "pass user@host, without an ssh:// prefix"
  [[ "$context_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail "invalid context name"
  command -v docker >/dev/null 2>&1 || fail "docker is required"
  if docker context inspect "$context_name" >/dev/null 2>&1; then
    fail "context '$context_name' already exists; select it or choose another name"
  fi

  docker context create "$context_name" \
    --description "whodat generic server over SSH" \
    --docker "host=ssh://${ssh_target}"
  printf '\nSelect it for this shell:\n  export DOCKER_CONTEXT=%s\n' "$context_name"
  printf 'Then verify it:\n  ./deploy/server/manage.sh check\n'
}

command_name="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command_name" in
  context-create)
    create_context "$@"
    ;;
  contexts)
    docker context ls
    ;;
  check)
    require_context
    remote_note
    printf 'Remote Docker server version: '
    docker version --format '{{.Server.Version}}'
    ;;
  deploy | up | down | logs | ps | migrate | shell | backup | restore | update)
    require_context
    require_env
    remote_note
    case "$command_name" in
      deploy)
        [[ $# -eq 0 ]] || fail "deploy takes no arguments"
        compose build
        compose up -d
        wait_for_health
        ;;
      up)
        [[ $# -eq 0 ]] || fail "up takes no arguments"
        compose up -d
        ;;
      down)
        [[ $# -eq 0 ]] || fail "down takes no arguments (volumes are always kept)"
        compose down
        ;;
      logs)
        compose logs --follow --tail=200 "$@"
        ;;
      ps)
        [[ $# -eq 0 ]] || fail "ps takes no arguments"
        compose ps
        ;;
      migrate)
        [[ $# -eq 0 ]] || fail "migrate takes no arguments"
        compose run --rm backend uv run alembic upgrade head
        ;;
      shell)
        [[ $# -le 1 ]] || fail "usage: manage.sh shell [backend|postgres|frontend|caddy]"
        service="${1:-backend}"
        case "$service" in
          backend | postgres | frontend | caddy) ;;
          *) fail "unknown service: $service" ;;
        esac
        compose exec "$service" sh
        ;;
      backup)
        [[ $# -le 1 ]] || fail "usage: manage.sh backup [directory]"
        "${script_dir}/backup.sh" "$@"
        ;;
      restore)
        [[ $# -eq 1 ]] || fail "usage: manage.sh restore <file.sql.gz>"
        restore_file="$1"
        [[ -f "$restore_file" && -r "$restore_file" ]] || fail "cannot read $restore_file"
        gzip -t -- "$restore_file" || fail "not a valid gzip backup: $restore_file"
        printf 'This replaces the database on remote context %s.\n' "$DOCKER_CONTEXT"
        printf 'Backup file: %s\n' "$restore_file"
        read -r -p 'Type yes to stop app containers and restore: ' confirmation
        [[ "$confirmation" == "yes" ]] || fail "restore cancelled"
        compose stop caddy frontend backend
        compose up -d postgres
        wait_for_health postgres
        # shellcheck disable=SC2016 # The remote shell expands these variables in Postgres.
        gzip -dc -- "$restore_file" | compose exec -T postgres sh -c \
          'exec psql --single-transaction --set=ON_ERROR_STOP=1 \
            --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"'
        compose up -d
        wait_for_health
        ;;
      update)
        [[ $# -eq 0 ]] || fail "update takes no arguments"
        compose pull postgres
        compose build --pull
        compose up -d
        wait_for_health
        ;;
    esac
    ;;
  "" | help | -h | --help)
    usage
    ;;
  *)
    usage >&2
    fail "unknown command: $command_name"
    ;;
esac
