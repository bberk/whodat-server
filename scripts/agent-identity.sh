#!/usr/bin/env bash
# Manage identity and credentials for agents and automated workflows.
# Supports GitHub App authentication (brads-bots) as well as any generic agent or human.
#
# Usage:
#   scripts/agent-identity.sh install     configure git author in the current worktree/repo
#   scripts/agent-identity.sh run <cmd>   run <cmd> with GH_TOKEN / GITHUB_TOKEN exported
#   scripts/agent-identity.sh whoami      print agent name and email
#   scripts/agent-identity.sh token       print the current auth token
#   scripts/agent-identity.sh email       print the agent's commit email
#
# Environment variables / .env:
#   BRADS_BOTS_APP_ID  Numeric GitHub App ID (e.g. 5364551). When set and private key exists,
#                      mints an App installation token so actions appear as brads-bots[bot].
#   BRADS_BOTS_KEY     Path to App private key (default: ~/.config/brads-bots/private-key.pem)
#   BRADS_BOTS_TOKEN   Direct App token override (used in tests)
#   AGENT_NAME         Generic agent display name (fallback: git user.name or "agent")
#   AGENT_EMAIL        Generic agent commit email (fallback: git user.email or "agent@...")
#   GH_TOKEN / GITHUB_TOKEN
#                      Standard token fallback when App ID is not configured.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Load BRADS_BOTS_APP_ID from .env if not in environment
if [[ -z "${BRADS_BOTS_APP_ID:-}" ]] && [[ -f "$repo_root/.env" ]]; then
  app_id_from_env="$(grep -E '^BRADS_BOTS_APP_ID=' "$repo_root/.env" | cut -d= -f2- | tr -d ' "\r' || true)"
  if [[ -n "$app_id_from_env" ]]; then
    export BRADS_BOTS_APP_ID="$app_id_from_env"
  fi
fi

die() {
  echo "agent-identity.sh: $*" >&2
  exit 1
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

api_request() {
  printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/vnd.github+json"\n' \
    "$1" | curl -fsS -K - -X "$2" "https://api.github.com$3"
}

has_app_config() {
  if [[ -n "${BRADS_BOTS_TOKEN:-}" ]]; then
    return 0
  fi
  local app_id="${BRADS_BOTS_APP_ID:-}"
  local key="${BRADS_BOTS_KEY:-$HOME/.config/brads-bots/private-key.pem}"
  [[ -n "$app_id" && -r "$key" ]]
}

mint_app_token() {
  if [[ -n "${BRADS_BOTS_TOKEN:-}" ]]; then
    echo "$BRADS_BOTS_TOKEN"
    return
  fi
  local app_id="${BRADS_BOTS_APP_ID:-}"
  local key="${BRADS_BOTS_KEY:-$HOME/.config/brads-bots/private-key.pem}"
  [[ -n "$app_id" ]] || die "BRADS_BOTS_APP_ID is required to mint token"
  [[ -r "$key" ]] || die "cannot read App private key at $key"

  local now header payload sig jwt repo installation_id
  now="$(date +%s)"
  header="$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | b64url)"
  payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$app_id" \
    | b64url)"
  sig="$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" -binary | b64url)"
  jwt="$header.$payload.$sig"

  repo="$(git remote get-url origin 2>/dev/null \
    | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##' || true)"
  if [[ -z "$repo" ]]; then
    repo="bberk/whodat-server"
  fi

  installation_id="$(api_request "$jwt" GET "/repos/$repo/installation" | jq -r .id)"
  [[ "$installation_id" =~ ^[0-9]+$ ]] || die "GitHub App is not installed on $repo"
  api_request "$jwt" POST "/app/installations/$installation_id/access_tokens" | jq -r .token
}

get_token() {
  if has_app_config; then
    mint_app_token
    return
  fi
  if [[ -n "${GH_TOKEN:-}" ]]; then
    echo "$GH_TOKEN"
    return
  fi
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "$GITHUB_TOKEN"
    return
  fi
  if command -v gh >/dev/null 2>&1; then
    local gh_tok
    gh_tok="$(gh auth token 2>/dev/null || true)"
    if [[ -n "$gh_tok" ]]; then
      echo "$gh_tok"
      return
    fi
  fi
  die "no auth token found. Set BRADS_BOTS_APP_ID, GH_TOKEN, or log in with 'gh auth login'"
}

get_name() {
  if has_app_config; then
    echo "brads-bots[bot]"
    return
  fi
  local name="${AGENT_NAME:-${GIT_AUTHOR_NAME:-}}"
  if [[ -z "$name" ]]; then
    name="$(git config user.name 2>/dev/null || true)"
  fi
  echo "${name:-agent}"
}

get_email() {
  if has_app_config; then
    echo "344180581+brads-bots[bot]@users.noreply.github.com"
    return
  fi
  local email="${AGENT_EMAIL:-${GIT_AUTHOR_EMAIL:-}}"
  if [[ -z "$email" ]]; then
    email="$(git config user.email 2>/dev/null || true)"
  fi
  echo "${email:-agent@users.noreply.github.com}"
}

is_main_checkout() {
  [[ "$(git rev-parse --git-dir 2>/dev/null)" == "$(git rev-parse --git-common-dir 2>/dev/null)" ]]
}

install_identity() {
  is_main_checkout && die "run 'install' in an agent worktree, not in the main checkout"
  local name email
  name="$(get_name)"
  email="$(get_email)"
  git config extensions.worktreeConfig true 2>/dev/null || true
  git config --worktree user.name "$name" 2>/dev/null || git config user.name "$name"
  git config --worktree user.email "$email" 2>/dev/null || git config user.email "$email"
  echo "agent-identity.sh: commits in this worktree will be authored by $name <$email>" >&2
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  install) install_identity ;;
  token) get_token ;;
  email) get_email ;;
  whoami)
    echo "$(get_name) <$(get_email)>"
    ;;
  run)
    [[ $# -gt 0 ]] || die "usage: agent-identity.sh run <command> [args...]"
    GH_TOKEN="$(get_token)"
    export GH_TOKEN
    exec "$@"
    ;;
  *)
    echo "usage: scripts/agent-identity.sh {install|run <cmd>|whoami|token|email}" >&2
    exit 64
    ;;
esac
