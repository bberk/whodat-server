#!/usr/bin/env bash
# Run an INDEPENDENT review of a pull request.
#
# Why this is "fresh eyes":
#   - a brand-new `opencode run` process and session (never --continue / --session),
#   - a separate git worktree checked out at the PR head,
#   - the reviewer agent definition is taken from `main`, never from the PR,
#   - a separate GitHub identity (REVIEWER_GH_TOKEN), because GitHub does not let an
#     account approve its own PR,
#   - the reviewer is told only the PR number; it never sees the author's session.
#
# Usage:  scripts/review.sh <pr-number>
# Env:    REVIEWER_GH_TOKEN  token for the reviewer GitHub account (required)
# Exit:   0 = approved, 2 = changes requested, 1 = error / no verdict
set -euo pipefail

pr="${1:?usage: scripts/review.sh <pr-number>}"
: "${REVIEWER_GH_TOKEN:?set REVIEWER_GH_TOKEN to a token for the reviewer GitHub account}"

for tool in gh git jq opencode; do
  command -v "$tool" >/dev/null 2>&1 || { echo "review.sh: '$tool' is required" >&2; exit 1; }
done

repo_root="$(git rev-parse --show-toplevel)"
export GH_TOKEN="$REVIEWER_GH_TOKEN"
unset AGENT_AUTOSHIP

reviewer_login="$(gh api user --jq .login)"
author_login="$(gh pr view "$pr" --json author --jq .author.login)"
if [[ "$reviewer_login" == "$author_login" ]]; then
  echo "review.sh: reviewer account ($reviewer_login) is the PR author; use a different GitHub account" >&2
  exit 1
fi

tmp="$(mktemp -d)"
cleanup() {
  git -C "$repo_root" worktree remove --force "$tmp/wt" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

git -C "$repo_root" fetch --quiet origin main "pull/$pr/head"
head_sha="$(git -C "$repo_root" rev-parse FETCH_HEAD)"
git -C "$repo_root" worktree add --quiet --detach "$tmp/wt" "$head_sha"

# Trust boundary: the reviewer's instructions come from main, not from the PR under review.
mkdir -p "$tmp/wt/.opencode/agents"
git -C "$repo_root" show origin/main:.opencode/agents/reviewer.md >"$tmp/wt/.opencode/agents/reviewer.md"

cd "$tmp/wt"
echo "review.sh: reviewing PR #$pr at $head_sha as $reviewer_login" >&2

opencode run --agent reviewer \
  "Review pull request #$pr of this repository (head commit $head_sha). Follow your reviewer instructions exactly and finish by submitting your verdict with gh pr review."

state="$(gh pr view "$pr" --json reviews | jq -r --arg login "$reviewer_login" --arg sha "$head_sha" '
  [.reviews[] | select(.author.login == $login and .commit.oid == $sha)] | last | .state // "NONE"')"

case "$state" in
  APPROVED)
    echo "review.sh: PR #$pr APPROVED at $head_sha" >&2
    exit 0
    ;;
  CHANGES_REQUESTED)
    echo "review.sh: PR #$pr CHANGES REQUESTED at $head_sha" >&2
    exit 2
    ;;
  *)
    echo "review.sh: reviewer did not submit a verdict for $head_sha (state: $state)" >&2
    exit 1
    ;;
esac
