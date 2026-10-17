#!/usr/bin/env bash
# Push the current branch to origin and make sure a pull request exists for it.
#
#   scripts/ship.sh                push, and open a DRAFT PR if none exists yet
#   scripts/ship.sh --ready        push, then mark the PR ready for review and label it
#                                  `ready-for-review` (the orchestrator's cue to start a review)
#   scripts/ship.sh --post-commit  git-hook mode (called by pre-commit's post-commit stage):
#                                  behaves like the default, but ONLY when AGENT_AUTOSHIP=1,
#                                  so human commits are never pushed unexpectedly
#
# Env:
#   AGENT_AUTOSHIP=1            enable hook mode (set this in the agents' environment)
#   SHIP_FORCE_WITH_LEASE=1     use --force-with-lease (only after rebasing YOUR OWN agent branch)
#
# Requires: git, gh (authenticated as the AUTHOR identity, not the reviewer).
set -euo pipefail

mode="draft"
case "${1:-}" in
  "") ;;
  --ready) mode="ready" ;;
  --post-commit)
    [[ "${AGENT_AUTOSHIP:-0}" == "1" ]] || exit 0
    ;;
  *)
    echo "usage: scripts/ship.sh [--ready | --post-commit]" >&2
    exit 64
    ;;
esac

command -v gh >/dev/null 2>&1 || { echo "ship.sh: the GitHub CLI (gh) is required" >&2; exit 1; }

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

if ! gh pr view "$branch" --json number >/dev/null 2>&1; then
  title="$(git log -1 --pretty=%s)"
  gh pr create --draft --base main --head "$branch" \
    --title "$title" --body-file .github/pull_request_template.md
fi

if [[ "$mode" == "ready" ]]; then
  gh pr ready "$branch" || true
  gh pr edit "$branch" --add-label "ready-for-review"
fi

gh pr view "$branch" --json url --jq .url
