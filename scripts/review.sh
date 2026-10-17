#!/usr/bin/env bash
# Run an INDEPENDENT review of a pull request.
#
# Why this is "fresh eyes":
#   - a brand-new `opencode run` process and session (never --continue / --session),
#   - a separate git worktree checked out at the PR head,
#   - the reviewer agent definition is taken from `main`, never from the PR,
#   - the reviewer is told only the PR number; it never sees the author's session.
#
# The reviewer posts its verdict as a GitHub review COMMENT (state COMMENTED). GitHub does not
# let an account approve its own pull request, and agents never merge, so a human reads the
# report and makes the formal approval and merge.
#
# Usage:  scripts/review.sh <pr-number>
# Exit:   0 = reviewed, no blocking issues; 2 = changes requested; 1 = error / no verdict
set -euo pipefail

pr="${1:?usage: scripts/review.sh <pr-number>}"

for tool in gh git jq opencode; do
  command -v "$tool" >/dev/null 2>&1 || { echo "review.sh: '$tool' is required" >&2; exit 1; }
done

repo_root="$(git rev-parse --show-toplevel)"
unset AGENT_AUTOSHIP

reviewer_login="$(gh api user --jq .login)"

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
  "Review pull request #$pr of this repository (head commit $head_sha). Follow your reviewer instructions exactly and finish by submitting your verdict with gh pr review --comment."

body="$(gh pr view "$pr" --json reviews | jq -r --arg login "$reviewer_login" --arg sha "$head_sha" '
  [.reviews[] | select(.author.login == $login and .commit.oid == $sha)] | last | .body // ""')"

if [[ -z "$body" ]]; then
  echo "review.sh: reviewer did not post a review for $head_sha" >&2
  exit 1
fi

verdict="$(printf '%s\n' "$body" \
  | grep -oiE 'verdict:[[:space:]]*(approved|changes requested)' | head -1 | tr 'A-Z' 'a-z')"

case "$verdict" in
  *approved)
    echo "review.sh: PR #$pr reviewed, no blocking issues, at $head_sha" >&2
    exit 0
    ;;
  *changes*requested)
    echo "review.sh: PR #$pr changes requested at $head_sha" >&2
    exit 2
    ;;
  *)
    echo "review.sh: reviewer posted a review with no parsable verdict for $head_sha" >&2
    exit 1
    ;;
esac
