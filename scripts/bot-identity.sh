#!/usr/bin/env bash
# Act as the `brads-bots` GitHub App instead of as the human, so that agent-authored commits,
# branches, and pull requests are not authored by the owner's account (GitHub will not let the
# owner approve their own work).
#
#   scripts/bot-identity.sh install     run ONCE in each agent worktree (not the main checkout):
#                                       commits made in this worktree are authored by
#                                       brads-bots[bot]. Only this worktree's config changes.
#   scripts/bot-identity.sh run <cmd>   run <cmd> with GH_TOKEN set to a fresh installation token
#                                       (for example: scripts/bot-identity.sh run gh pr view 12)
#   scripts/bot-identity.sh token       print a fresh installation token (prefer `run`)
#   scripts/bot-identity.sh email       print the bot's commit email
#
# Env:
#   BRADS_BOTS_APP_ID   numeric App ID of brads-bots (required for token/run)
#   BRADS_BOTS_KEY      path to the App private key
#                       (default: ~/.config/brads-bots/private-key.pem)
#
# The installation is looked up from the `origin` remote, so the App must be installed on this
# repository. Tokens last one hour and are never written to disk or passed on a command line.
set -euo pipefail

bot_slug="brads-bots"
bot_id="344180581"
bot_name="${bot_slug}[bot]"
bot_email="${bot_id}+${bot_slug}[bot]@users.noreply.github.com"

die() {
  echo "bot-identity.sh: $*" >&2
  exit 1
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# api <jwt> <method> <path>: the JSON response, with the JWT passed through curl's stdin config
# so it does not appear in the process list.
api() {
  printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/vnd.github+json"\n' \
    "$1" | curl -fsS -K - -X "$2" "https://api.github.com$3"
}

mint_token() {
  local app_id="${BRADS_BOTS_APP_ID:-}"
  local key="${BRADS_BOTS_KEY:-$HOME/.config/brads-bots/private-key.pem}"
  [[ -n "$app_id" ]] || die "set BRADS_BOTS_APP_ID to the numeric App ID of $bot_slug"
  [[ -r "$key" ]] || die "cannot read the App private key at $key"

  local now header payload sig jwt repo installation_id
  now="$(date +%s)"
  header="$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | b64url)"
  payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$app_id" \
    | b64url)"
  sig="$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" -binary | b64url)"
  jwt="$header.$payload.$sig"

  repo="$(git remote get-url origin \
    | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
  installation_id="$(api "$jwt" GET "/repos/$repo/installation" | jq -r .id)"
  [[ "$installation_id" =~ ^[0-9]+$ ]] || die "$bot_slug is not installed on $repo"
  api "$jwt" POST "/app/installations/$installation_id/access_tokens" | jq -r .token
}

is_main_checkout() {
  [[ "$(git rev-parse --git-dir)" == "$(git rev-parse --git-common-dir)" ]]
}

install_identity() {
  is_main_checkout && die "run 'install' in an agent worktree, not in the main checkout"
  git config extensions.worktreeConfig true
  git config --worktree user.name "$bot_name"
  git config --worktree user.email "$bot_email"
  echo "bot-identity.sh: commits in this worktree will be authored by $bot_name" >&2
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  install) install_identity ;;
  token) mint_token ;;
  email) echo "$bot_email" ;;
  run)
    [[ $# -gt 0 ]] || die "usage: bot-identity.sh run <command> [args...]"
    GH_TOKEN="$(mint_token)"
    export GH_TOKEN
    exec "$@"
    ;;
  *)
    echo "usage: scripts/bot-identity.sh {install|run <cmd>|token|email}" >&2
    exit 64
    ;;
esac
