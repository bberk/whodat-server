#!/usr/bin/env bash
# Squash-merge a pull request if, and only if, it is ready:
#   - open and not a draft
#   - every CI check passed (none pending, none failed, at least one exists)
#   - it does not modify governance files (the rules, gates, and scripts themselves);
#     those need a human: re-run with --allow-governance after reviewing them yourself
#
# A human runs this after reading the independent reviewer's report; reviewers never approve or
# merge. This enforces the CI and governance gates client-side so they hold even where GitHub
# cannot enforce them (e.g. private repos on a plan without branch protection).
#
# Usage: scripts/merge.sh <pr-number> [--allow-governance]
# Requires: gh (authenticated with write access), jq.
set -euo pipefail

pr="${1:?usage: scripts/merge.sh <pr-number> [--allow-governance]}"
allow_governance=0
[[ "${2:-}" == "--allow-governance" ]] && allow_governance=1

for tool in gh jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "merge.sh: '$tool' is required" >&2; exit 1; }
done

fail() {
  echo "merge.sh: NOT merging #$pr: $*" >&2
  exit 1
}

json="$(gh pr view "$pr" --json state,isDraft,headRefOid,statusCheckRollup,files)"

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

gh pr merge "$pr" --squash --delete-branch --match-head-commit "$head_sha"
echo "merge.sh: merged #$pr (squash) at $head_sha" >&2
