#!/usr/bin/env bash
# Merge a pull request if, and only if, it is ready:
#   - open and not a draft
#   - every CI check passed (none pending, none failed, at least one exists)
#   - it does not modify governance files (the rules, gates, and scripts themselves);
#     those need a human: re-run with --allow-governance after reviewing them yourself
#
# A human runs this after reading the independent reviewer's report; reviewers never approve or
# merge. This enforces the CI and governance gates client-side so they hold even where GitHub
# cannot enforce them (e.g. private repos on a plan without branch protection).
#
# Merge method: rebase by default, which keeps the branch's own commits and main's history linear.
# --squash collapses the whole branch into one commit. There is no merge commit: the `main
# protection` ruleset requires linear history.
#
# After a successful merge the author's local branch and worktree are cleaned up through
# scripts/cleanup.sh, because GitHub only deletes the remote branch. Merges made in the web UI do
# not run this script at all; run `scripts/cleanup.sh` (no arguments) afterwards.
#
# Usage: scripts/merge.sh <pr-number> [--rebase | --squash] [--allow-governance]
# Requires: gh (authenticated with write access), jq.
set -euo pipefail

pr="${1:?usage: scripts/merge.sh <pr-number> [--rebase | --squash] [--allow-governance]}"
shift

method="rebase"
allow_governance=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebase) method="rebase" ;;
    --squash) method="squash" ;;
    --allow-governance) allow_governance=1 ;;
    --merge)
      echo "merge.sh: --merge is not available: the 'main protection' ruleset requires linear" >&2
      echo "          history, so GitHub rejects merge commits. Use --rebase (default) or --squash." >&2
      exit 64
      ;;
    *)
      echo "merge.sh: unknown option '$1'" >&2
      exit 64
      ;;
  esac
  shift
done

for tool in gh jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "merge.sh: '$tool' is required" >&2; exit 1; }
done

fail() {
  echo "merge.sh: NOT merging #$pr: $*" >&2
  exit 1
}

json="$(gh pr view "$pr" --json state,isDraft,headRefOid,headRefName,statusCheckRollup,files)"

[[ "$(jq -r .state <<<"$json")" == "OPEN" ]] || fail "PR is not open"
[[ "$(jq -r .isDraft <<<"$json")" == "false" ]] || fail "PR is still a draft"

head_sha="$(jq -r .headRefOid <<<"$json")"

checks="$(jq -r '
  [.statusCheckRollup[] | (.conclusion // .state)]
  | if length == 0 then "NONE"
    elif all(. == "SUCCESS" or . == "SKIPPED" or . == "NEUTRAL") then "OK"
    else "NOT_GREEN" end' <<<"$json")"
case "$checks" in
  OK) ;;
  NONE) fail "no CI checks have reported yet" ;;
  *) fail "CI checks are pending or failing" ;;
esac

if [[ "$allow_governance" -eq 0 ]]; then
  governance="$(jq -r '.files[].path' <<<"$json" \
    | grep -E '^(AGENTS\.md|SPEC\.md|ACCEPTANCE\.md|ARCHITECTURE\.md|\.opencode/|\.github/|scripts/|\.pre-commit-config\.yaml)' || true)"
  [[ -z "$governance" ]] || fail "touches governance files, a human must merge it (--allow-governance):
$governance"
fi

gh pr merge "$pr" "--$method" --delete-branch --match-head-commit "$head_sha"
echo "merge.sh: merged #$pr ($method) at $head_sha" >&2

# `gh --delete-branch` removes the local branch only when it is checked out in this repository.
# When the author worked in another worktree (the usual case) it is still there, so finish the job.
# Cleanup is best effort: a failure must never make a completed merge look unsuccessful.
head_ref="$(jq -r '.headRefName // empty' <<<"$json")"
if [[ -n "$head_ref" ]]; then
  "$(dirname "$0")/cleanup.sh" "$head_ref" >&2 || true
fi
