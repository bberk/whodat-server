#!/usr/bin/env bash
# Manage identity and credentials for agents and automated workflows.
# Works with any agent (Antigravity, Claude Code, Codex, Opencode, or humans).
#
# Usage:
#   scripts/agent-identity.sh install     configure git author in the current worktree/repo
#   scripts/agent-identity.sh run <cmd>   run <cmd> with GH_TOKEN / GITHUB_TOKEN exported
#   scripts/agent-identity.sh whoami      print agent name and email
#   scripts/agent-identity.sh token       print the current auth token
#   scripts/agent-identity.sh email       print the agent's commit email
#
# Environment variables:
#   AGENT_NAME       Agent display name (default: GIT_AUTHOR_NAME, git user.name, or "agent")
#   AGENT_EMAIL      Agent commit email (default: GIT_AUTHOR_EMAIL, git user.email, or "agent@users.noreply.github.com")
#   GH_TOKEN / GITHUB_TOKEN / BRADS_BOTS_TOKEN
#                    GitHub token to use. If not set, checks `gh auth token` when gh is available.
set -euo pipefail

die() {
  echo "agent-identity.sh: $*" >&2
  exit 1
}

# Resolve agent name
agent_name="${AGENT_NAME:-${GIT_AUTHOR_NAME:-}}"
if [[ -z "$agent_name" ]]; then
  agent_name="$(git config user.name 2>/dev/null || true)"
fi
if [[ -z "$agent_name" ]]; then
  agent_name="agent"
fi

# Resolve agent email
agent_email="${AGENT_EMAIL:-${GIT_AUTHOR_EMAIL:-}}"
if [[ -z "$agent_email" ]]; then
  agent_email="$(git config user.email 2>/dev/null || true)"
fi
if [[ -z "$agent_email" ]]; then
  agent_email="agent@users.noreply.github.com"
fi

get_token() {
  if [[ -n "${GH_TOKEN:-}" ]]; then
    echo "$GH_TOKEN"
    return
  fi
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "$GITHUB_TOKEN"
    return
  fi
  if [[ -n "${BRADS_BOTS_TOKEN:-}" ]]; then
    echo "$BRADS_BOTS_TOKEN"
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
  echo ""
}

install_identity() {
  local is_wt=0
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local git_dir git_common_dir
    git_dir="$(git rev-parse --git-dir 2>/dev/null || true)"
    git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
    if [[ -n "$git_dir" && -n "$git_common_dir" && "$git_dir" != "$git_common_dir" ]]; then
      is_wt=1
    fi
  fi

  if [[ "$is_wt" -eq 1 ]]; then
    git config extensions.worktreeConfig true
    git config --worktree user.name "$agent_name"
    git config --worktree user.email "$agent_email"
    echo "agent-identity.sh: commits in this worktree will be authored by $agent_name <$agent_email>" >&2
  else
    git config user.name "$agent_name" 2>/dev/null || true
    git config user.email "$agent_email" 2>/dev/null || true
    echo "agent-identity.sh: commits will be authored by $agent_name <$agent_email>" >&2
  fi
}

run_cmd() {
  [[ $# -gt 0 ]] || die "usage: agent-identity.sh run <command> [args...]"
  local tok
  tok="$(get_token)"
  if [[ -n "$tok" ]]; then
    export GH_TOKEN="$tok"
    export GITHUB_TOKEN="$tok"
  fi
  exec "$@"
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  install) install_identity ;;
  whoami) echo "$agent_name <$agent_email>" ;;
  email) echo "$agent_email" ;;
  token) get_token ;;
  run) run_cmd "$@" ;;
  *)
    echo "usage: scripts/agent-identity.sh {install|run <cmd>|whoami|token|email}" >&2
    exit 64
    ;;
esac
