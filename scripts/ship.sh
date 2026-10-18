#!/usr/bin/env bash
# Push the current branch to origin.
#
#   scripts/ship.sh            push the branch
#   scripts/ship.sh --ready    push, then mark the PR ready for review and label it
#                              `ready-for-review` (the orchestrator's cue to start a review)
#
# Nothing runs on your behalf: there is no post-commit hook, so pushing is an explicit step you take
# before opening or updating a pull request. This script also never opens the PR — open a draft PR
# with `gh` (as the App identity); see .opencode/pull-requests.md.
#
# Identity: pushes and `gh` calls act as the brads-bots GitHub App (see scripts/bot-identity.sh),
# and the branch's commits must be authored by that App. Run `scripts/bot-identity.sh install`
# once in the worktree before committing.
#
# Env:
#   SHIP_FORCE_WITH_LEASE=1     use --force-with-lease (only after rebasing YOUR OWN agent branch)
#   BRADS_BOTS_APP_ID           App ID of brads-bots (required; see scripts/bot-identity.sh)
#
# Requires: git, jq; gh only for --ready.
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
    echo "ship.sh: refusing to ship '$branch' (work on an agent/<task>-<slug> branch)" >&2
    exit 1
    ;;
esac

bot_email="$("$here/bot-identity.sh" email)"
base="$(git merge-base origin/main HEAD)" || {
  echo "ship.sh: cannot find origin/main to compare against" >&2
  exit 1
}
foreign="$(git log --format='%h %ae' "$base..HEAD" | grep -vF " $bot_email" || true)"
if [[ -n "$foreign" ]]; then
  echo "ship.sh: refusing to push commits not authored by $bot_email:" >&2
  echo "$foreign" >&2
  echo "          run scripts/bot-identity.sh install in this worktree, then re-author them:" >&2
  echo "          git rebase origin/main --exec 'git commit --amend --no-edit --reset-author'" >&2
  exit 1
fi

GH_TOKEN="$("$here/bot-identity.sh" token)"
export GH_TOKEN

push_args=(--set-upstream origin "$branch")
if [[ "${SHIP_FORCE_WITH_LEASE:-0}" == "1" ]]; then
  push_args=(--force-with-lease "${push_args[@]}")
fi
# Push with the App's token only: clear the configured helpers so the human's credentials are
# never used. The token reaches git through the environment, not the command line.
git -c credential.helper= \
  -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f' \
  push "${push_args[@]}"

if [[ "$mode" != "ready" ]]; then
  echo "ship.sh: pushed $branch (open or update the PR with gh via bot-identity.sh;" >&2
  echo "          see .opencode/pull-requests.md)" >&2
  if command -v gh >/dev/null 2>&1 && gh pr view "$branch" --json url >/dev/null 2>&1; then
    gh pr view "$branch" --json url --jq .url
  fi
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "ship.sh: 'gh' is required for --ready" >&2; exit 1; }
if ! gh pr view "$branch" --json number >/dev/null 2>&1; then
  echo "ship.sh: no PR for '$branch' yet; open a draft PR with gh first" >&2
  echo "          (see .opencode/pull-requests.md), then run --ready again" >&2
  exit 1
fi

gh pr ready "$branch"
gh pr edit "$branch" --add-label "ready-for-review"
gh pr view "$branch" --json url --jq .url
