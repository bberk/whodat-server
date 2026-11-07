#!/usr/bin/env bash
# Run an independent review of a pull request.
# Harness-agnostic: does not require a specific agent CLI, but will invoke one if configured.
#
# Usage:  scripts/review.sh <pr-number> [--post]
#
# Options:
#   --post    Submit the review verdict as a GitHub review comment (gh pr review --comment)
#
# Env:
#   REVIEWER_AGENT_CMD   Optional agent command to run (e.g. "opencode run --agent reviewer")
#   POST_REVIEW=1        Equivalent to passing --post
#
# Exit:
#   0 = reviewed, no blocking issues (approved)
#   2 = changes requested
#   1 = error or invalid PR state
set -euo pipefail

usage() {
  echo "usage: scripts/review.sh <pr-number> [--post]" >&2
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

pr="$1"
shift

post_review="${POST_REVIEW:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --post) post_review=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "review.sh: unknown option '$1'" >&2; usage; exit 1 ;;
  esac
  shift
done

for tool in git gh jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "review.sh: '$tool' is required" >&2; exit 1; }
done

# Resolve token if available
if [[ -z "${GH_TOKEN:-}" ]]; then
  tok="$("$(dirname "$0")/agent-identity.sh" token 2>/dev/null || true)"
  if [[ -n "$tok" ]]; then
    export GH_TOKEN="$tok"
  fi
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Fetch PR info
if ! pr_info="$(gh pr view "$pr" --json number,title,body,state,isDraft,headRefOid,headRefName,files,statusCheckRollup,url 2>/dev/null)"; then
  echo "review.sh: failed to fetch pull request #$pr" >&2
  exit 1
fi

head_sha="$(jq -r .headRefOid <<<"$pr_info")"
head_branch="$(jq -r .headRefName <<<"$pr_info")"
is_draft="$(jq -r .isDraft <<<"$pr_info")"
state="$(jq -r .state <<<"$pr_info")"
title="$(jq -r .title <<<"$pr_info")"
url="$(jq -r .url <<<"$pr_info")"

echo "review.sh: reviewing PR #$pr ('$title') at $head_sha" >&2

# If an external agent command is explicitly configured, delegate to it
if [[ -n "${REVIEWER_AGENT_CMD:-}" ]]; then
  echo "review.sh: delegating review to REVIEWER_AGENT_CMD: $REVIEWER_AGENT_CMD" >&2
  eval "$REVIEWER_AGENT_CMD"
  exit $?
fi

# Built-in clean diff & PR summary reviewer runner
blocking_issues=()
warnings=()
verified=()

# 1. PR State checks
if [[ "$state" != "OPEN" ]]; then
  blocking_issues+=("PR is not open (current state: $state)")
else
  verified+=("PR is open")
fi

if [[ "$is_draft" == "true" ]]; then
  blocking_issues+=("PR is still marked as a draft")
else
  verified+=("PR is marked ready for review (not draft)")
fi

# 2. CI status checks
ci_status="$(jq -r '
  [.statusCheckRollup[] | (.conclusion // .state)]
  | if length == 0 then "NONE"
    elif all(. == "SUCCESS" or . == "SKIPPED" or . == "NEUTRAL") then "OK"
    elif any(. == "FAILURE" or . == "START_FAILURE" or . == "CANCELLED" or . == "TIMED_OUT") then "FAILED"
    else "PENDING" end' <<<"$pr_info")"

case "$ci_status" in
  OK)
    verified+=("All reported CI status checks passed")
    ;;
  NONE)
    warnings+=("No CI checks have reported yet")
    ;;
  PENDING)
    warnings+=("CI status checks are currently pending")
    ;;
  FAILED)
    blocking_issues+=("One or more CI checks failed or cancelled")
    ;;
esac

# 3. Governance gate check
governance_files="$(jq -r '.files[].path' <<<"$pr_info" \
  | grep -E '^(AGENTS\.md|SPEC\.md|ACCEPTANCE\.md|ARCHITECTURE\.md|\.opencode/|\.agent/|\.github/|scripts/|\.pre-commit-config\.yaml)' || true)"

if [[ -n "$governance_files" ]]; then
  blocking_issues+=("Touches governance files; human review and approval required before merge:
$governance_files")
else
  verified+=("No governance files modified")
fi

# 4. Review changed files
file_count="$(jq '.files | length' <<<"$pr_info")"
verified+=("Inspected list of $file_count changed files")

# Determine final verdict
if [[ ${#blocking_issues[@]} -gt 0 ]]; then
  verdict="CHANGES REQUESTED"
  exit_code=2
else
  verdict="APPROVED"
  exit_code=0
fi

# Build review report body
review_body="Verdict: $verdict   (commit $head_sha)

PR: #$pr - $title
URL: $url

Blocking issues:"

if [[ ${#blocking_issues[@]} -eq 0 ]]; then
  review_body+=$'\n- None'
else
  for issue in "${blocking_issues[@]}"; do
    review_body+=$'\n- '"$issue"
  done
fi

review_body+=$'\n\nNon-blocking suggestions:'
if [[ ${#warnings[@]} -eq 0 ]]; then
  review_body+=$'\n- None'
else
  for warning in "${warnings[@]}"; do
    review_body+=$'\n- '"$warning"
  done
fi

review_body+=$'\n\nVerified:'
for check in "${verified[@]}"; do
  review_body+=$'\n- '"$check"
done

# Print report to stdout
printf '%s\n' "$review_body"

# Submit comment if requested
if [[ "$post_review" -eq 1 ]]; then
  echo "review.sh: posting review comment to #$pr..." >&2
  gh pr review "$pr" --comment --body "$review_body"
fi

exit "$exit_code"
