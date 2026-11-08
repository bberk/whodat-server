#!/usr/bin/env bash
# Push the current branch to origin.
#
#   scripts/ship.sh            push the branch
#   scripts/ship.sh --ready    push, then mark the PR ready for review and label it
#                              `ready-for-review` (the orchestrator's cue to start a review)
#
# Env:
#   SHIP_FORCE_WITH_LEASE=1     use --force-with-lease (only after rebasing your branch)
#   ALLOW_ANY_AUTHOR=1          skip author email validation
#   GH_TOKEN / GITHUB_TOKEN     auth token for git push and gh (optional)
#
# Requires: git; gh only for --ready or viewing PR url.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

mode="push"
case "${1:-}" in
  "") ;;
  --ready) mode="ready" ;;
  *)
    echo "usage: scripts/ship.sh [--ready]" >&2
    exit 64
    ;;
esac

branch="$(git rev-parse --abbrev-ref HEAD)"
case "$branch" in
  main | master | HEAD)
    echo "ship.sh: refusing to ship '$branch' (work on an agent/<task>-<slug> or feature branch)" >&2
    exit 1
    ;;
esac

# Validate author email against configured agent identity
agent_email="$("$here/agent-identity.sh" email 2>/dev/null || true)"
if [[ -n "$agent_email" && "${ALLOW_ANY_AUTHOR:-0}" != "1" ]]; then
  base="$(git merge-base origin/main HEAD 2>/dev/null || true)"
  if [[ -n "$base" ]]; then
    foreign="$(git log --format='%h %ae' "$base..HEAD" | grep -vF " $agent_email" || true)"
    if [[ -n "$foreign" ]]; then
      echo "ship.sh: refusing to push commits not authored by $agent_email:" >&2
      echo "$foreign" >&2
      echo "          run scripts/agent-identity.sh install in this worktree, then re-author them:" >&2
      echo "          git rebase origin/main --exec 'git commit --amend --no-edit --reset-author'" >&2
      exit 1
    fi
  fi
fi

# Resolve token if available
if [[ -z "${GH_TOKEN:-}" ]]; then
  tok="$("$here/agent-identity.sh" token 2>/dev/null || true)"
  if [[ -n "$tok" ]]; then
    export GH_TOKEN="$tok"
  fi
fi

push_args=(--set-upstream origin "$branch")
if [[ "${SHIP_FORCE_WITH_LEASE:-0}" == "1" ]]; then
  push_args=(--force-with-lease "${push_args[@]}")
fi

if [[ -n "${GH_TOKEN:-}" ]]; then
  git -c credential.helper= \
    -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f' \
    push "${push_args[@]}"
else
  git push "${push_args[@]}"
fi

if [[ "$mode" != "ready" ]]; then
  echo "ship.sh: pushed $branch" >&2
  if command -v gh >/dev/null 2>&1 && gh pr view "$branch" --json url >/dev/null 2>&1; then
    gh pr view "$branch" --json url --jq .url
  fi
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "ship.sh: 'gh' is required for --ready" >&2; exit 1; }
if ! gh pr view "$branch" --json number >/dev/null 2>&1; then
  echo "ship.sh: no PR for '$branch' yet; open a PR with gh first, then run --ready again" >&2
  exit 1
fi

pr_author_is_bot="$(gh pr view "$branch" --json author --jq '.author.is_bot // false' 2>/dev/null || true)"
pr_author_login="$(gh pr view "$branch" --json author --jq '.author.login // ""' 2>/dev/null || true)"
if [[ "$pr_author_is_bot" != "true" && "$pr_author_login" != "app/brads-bots" && "$pr_author_login" != "brads-bots"* ]]; then
  echo "ship.sh: refusing --ready: PR is authored by '$pr_author_login' (not a bot)." >&2
  echo "         GitHub prevents authors from reviewing or approving their own PRs." >&2
  echo "         Re-create the PR using: scripts/agent-identity.sh run gh pr create" >&2
  exit 1
fi

gh pr ready "$branch"
gh pr edit "$branch" --add-label "ready-for-review"
gh pr view "$branch" --json url --jq .url
