#!/usr/bin/env bash
# Deploy one commit of the production stack on the Oracle Cloud VM.
#
#   deploy/deploy.sh <full-40-character-git-sha>
#
# Run from the repository checkout on the VM. GitHub Actions uploads this script to a temporary
# path and runs it with the checkout as the working directory (see .github/workflows/deploy.yml).
# The script fetches and hard-resets the checkout to <sha>, rebuilds the images, restarts the
# stack, and requires the public health endpoint to answer. If any step fails it resets back to
# the commit that was deployed before and redeploys that.
#
# A deploy is successful only when `https://$DOMAIN/health` answers. The container-local check is
# logged as diagnostics to separate an application failure from a Caddy/DNS/certificate failure;
# it never turns a failed public check into a success.
#
# Secrets are read only through deploy/.env (by Docker Compose) and are never printed. The
# `:?` guards in deploy/docker-compose.prod.yml make a missing value fail loudly.
set -euo pipefail

readonly USAGE='usage: deploy/deploy.sh <40-character-git-sha>'
readonly HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-300}"
readonly HEALTH_POLL_SECONDS="${HEALTH_POLL_SECONDS:-5}"
# The local check only labels the failure, so it gets a short deadline instead of the full one.
readonly DIAGNOSTIC_TIMEOUT_SECONDS="${DIAGNOSTIC_TIMEOUT_SECONDS:-15}"

if [[ $# -ne 1 ]]; then
  echo "$USAGE" >&2
  exit 64
fi

target_sha="$1"
if [[ ! "$target_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "deploy: expected a full 40-character lowercase commit SHA, got '$target_sha'" >&2
  exit 64
fi

# This script resets the checkout that contains it, which can rewrite the running file. Re-exec
# from a private copy so git never modifies a script that bash is still reading.
if [[ "${WHODAT_DEPLOY_REEXEC:-0}" != "1" ]]; then
  tmp_script="$(mktemp "${TMPDIR:-/tmp}/whodat-deploy.XXXXXX.sh")"
  cp "${BASH_SOURCE[0]}" "$tmp_script"
  chmod 700 "$tmp_script"
  set +e
  WHODAT_DEPLOY_REEXEC=1 bash "$tmp_script" "$@"
  status=$?
  set -e
  rm -f "$tmp_script"
  exit "$status"
fi

die() {
  echo "deploy: $*" >&2
  exit 1
}

if repo_root="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)" &&
  [[ -f "$repo_root/deploy/docker-compose.prod.yml" ]]; then
  :
else
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$repo_root"

compose_file="$repo_root/deploy/docker-compose.prod.yml"
env_file="$repo_root/deploy/.env"
[[ -f "$compose_file" ]] || die "missing $compose_file"
[[ -f "$env_file" ]] || die "missing $env_file (copy deploy/.env.example and fill it in)"
command -v docker >/dev/null 2>&1 || die "docker is not installed"
command -v curl >/dev/null 2>&1 || die "curl is not installed"
docker compose version >/dev/null 2>&1 || die "the Docker Compose plugin is not installed"

compose() {
  docker compose -f "$compose_file" --env-file "$env_file" "$@"
}

# Read only the public hostname; DATABASE_URL, SECRET_KEY, and the other values stay unread here.
domain="$(sed -n 's/^DOMAIN=//p' "$env_file" | tail -n 1 | tr -d '\r')"
[[ -n "$domain" ]] || die "DOMAIN is not set in $env_file"

state_dir="${DEPLOY_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/whodat-deploy}"
install -d -m 700 "$state_dir"

previous_sha="$(git rev-parse HEAD)"
printf '%s\n' "$previous_sha" >"$state_dir/previous-sha"

build_and_up() {
  # Images build on the VM (ARM64). --pull keeps the pinned base images current.
  compose build --pull || return 1
  compose up -d --remove-orphans || return 1
}

wait_for_https_health() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if curl -fsS --max-time 5 -o /dev/null "https://$domain/health"; then
      return 0
    fi
    sleep "$HEALTH_POLL_SECONDS"
  done
  return 1
}

wait_for_local_health() {
  # Diagnostics only: ask the backend container directly over HTTP, without publishing a port, to
  # report whether the failure is inside the app or in front of it (Caddy, DNS, certificate).
  local timeout="${1:-$DIAGNOSTIC_TIMEOUT_SECONDS}"
  local deadline=$((SECONDS + timeout))
  while ((SECONDS < deadline)); do
    if compose exec -T backend python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep "$HEALTH_POLL_SECONDS"
  done
  return 1
}

# Deploy <sha> and wait for it to become healthy. Called from an `if`, so every critical command
# returns explicitly: `set -e` does not abort inside a condition context.
deploy_sha() {
  local sha="$1"
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    echo "deploy: commit $sha is not available in this checkout" >&2
    return 1
  fi
  git reset --hard "$sha" || return 1
  build_and_up || return 1
  if wait_for_https_health; then
    return 0
  fi
  echo "deploy: https://$domain/health did not answer within ${HEALTH_TIMEOUT_SECONDS}s" >&2
  if wait_for_local_health; then
    echo "deploy: diagnostics: the backend answers http://localhost:8000/health in its container," >&2
    echo "deploy: diagnostics: so the failure is in Caddy, DNS, port 80/443, or certificate issuance" >&2
  else
    echo "deploy: diagnostics: the backend container does not answer its internal health check either" >&2
  fi
  echo "deploy: the public HTTPS endpoint is required, so this deploy failed" >&2
  return 1
}

echo "deploy: deploying $target_sha (previous $previous_sha)" >&2
# The commit exists on GitHub but not necessarily in the VM's clone yet. Fetch once; the
# rollback path below only ever needs a commit that is already local.
git fetch --prune origin || die "git fetch origin failed"
if ! git cat-file -e "$target_sha^{commit}" 2>/dev/null; then
  die "commit $target_sha is not available after fetching origin"
fi
if deploy_sha "$target_sha"; then
  printf 'deploy: %s is healthy at https://%s\n' "$target_sha" "$domain"
  exit 0
fi

echo "deploy: $target_sha failed; rolling back to $previous_sha" >&2
if [[ "$previous_sha" == "$target_sha" ]]; then
  echo "deploy: nothing to roll back to; the stack is left on the failed commit" >&2
  exit 1
fi
if ! deploy_sha "$previous_sha"; then
  echo "deploy: rollback to $previous_sha also failed to become healthy" >&2
  exit 1
fi
printf 'deploy: rolled back to %s\n' "$previous_sha" >&2
exit 1
