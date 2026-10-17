#!/usr/bin/env bash
# Push the current branch to origin.
#
#   scripts/ship.sh            push the branch
#   scripts/ship.sh --ready    push, then mark the PR ready for review and label it
#                              `ready-for-review` (the orchestrator's cue to start a review)
#
# Nothing runs on your behalf: there is no post-commit hook, so pushing is an explicit step you take
# before opening or updating a pull request. This script also never opens the PR — open a draft PR
# through the GitHub MCP tools, or `gh`; see .opencode/pull-requests.md.
#
# Env:
#   SHIP_FORCE_WITH_LEASE=1     use --force-with-lease (only after rebasing YOUR OWN agent branch)
#
# Requires: git; gh only for --ready (authenticated as the AUTHOR identity, not the reviewer).
set -euo pipefail

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
    echo "ship.sh: refusing to ship '$branch' (work on an agent/<task>-<slug> branch)" >&2
    exit 1
    ;;
esac

push_args=(--set-upstream origin "$branch")
if [[ "${SHIP_FORCE_WITH_LEASE:-0}" == "1" ]]; then
  push_args=(--force-with-lease "${push_args[@]}")
fi
git push "${push_args[@]}"

if [[ "$mode" != "ready" ]]; then
  echo "ship.sh: pushed $branch (open or update the PR with the GitHub MCP tools;" >&2
  echo "          see .opencode/pull-requests.md)" >&2
  if command -v gh >/dev/null 2>&1 && gh pr view "$branch" --json url >/dev/null 2>&1; then
    gh pr view "$branch" --json url --jq .url
  fi
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "ship.sh: 'gh' is required for --ready" >&2; exit 1; }
if ! gh pr view "$branch" --json number >/dev/null 2>&1; then
  echo "ship.sh: no PR for '$branch' yet; open a draft PR with the GitHub MCP tools" >&2
  echo "          (see .opencode/pull-requests.md), then run --ready again" >&2
  exit 1
fi

gh pr ready "$branch"
gh pr edit "$branch" --add-label "ready-for-review"
gh pr view "$branch" --json url --jq .url
