#!/usr/bin/env bash
# One-time GitHub repository setup. Run this YOURSELF as the repo owner/admin
# (after `gh auth login`); agents must not run it.
#
# Usage: scripts/setup-github.sh [owner/repo]     (defaults to the repo in the current directory)
#
# What it does:
#   1. squash-merge only, auto-delete merged branches
#   2. creates the `ready-for-review` label
#   3. restricts the default GITHUB_TOKEN of Actions to read-only
#   4. creates a ruleset on the default branch: PR required, 1 approval from someone other than
#      the author, stale approvals dismissed on new pushes, required CI checks, linear history,
#      no force-push, no deletion
#
# Step 4 needs a public repo, or a paid plan (GitHub Pro/Team) for a private repo. If GitHub
# refuses, the script says so and carries on: scripts/merge.sh still enforces the same
# rules client-side, but nothing stops a determined agent or person pushing to main directly.
set -euo pipefail

command -v gh >/dev/null 2>&1 || { echo "gh (GitHub CLI) is required" >&2; exit 1; }
repo="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
echo "Configuring $repo"

echo "1/4 merge settings"
gh repo edit "$repo" \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge

echo "2/4 labels"
gh label create "ready-for-review" --repo "$repo" --color "0e8a16" \
  --description "Author finished; awaiting independent review" --force

echo "3/4 Actions default token -> read-only"
gh api --method PUT "repos/$repo/actions/permissions/workflow" \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false >/dev/null

echo "4/4 ruleset on the default branch"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/ruleset.json" <<'JSON'
{
  "name": "main protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "pre-commit" },
          { "context": "backend (sqlite)" },
          { "context": "backend (postgres)" },
          { "context": "frontend" }
        ]
      }
    }
  ]
}
JSON

existing_id="$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name == "main protection") | .id' 2>"$tmp/err" || true)"
if grep -q "Upgrade to GitHub Pro" "$tmp/err" 2>/dev/null; then
  cat >&2 <<'MSG'

!! GitHub does not offer rulesets/branch protection for this repo on its current plan.
   (Rulesets work on public repos on the Free plan, and on private repos with Pro/Team.)
   Options: make the repo public (only if nothing secret is in it), upgrade the plan,
   or accept client-side enforcement only (scripts/merge.sh). See docs/GITHUB_SETUP.md.
MSG
  exit 0
fi

if [[ -n "$existing_id" ]]; then
  gh api --method PUT "repos/$repo/rulesets/$existing_id" --input "$tmp/ruleset.json" >/dev/null
  echo "updated existing ruleset $existing_id"
elif gh api --method POST "repos/$repo/rulesets" --input "$tmp/ruleset.json" >/dev/null 2>"$tmp/err"; then
  echo "created ruleset"
elif grep -q "Upgrade to GitHub Pro" "$tmp/err"; then
  echo "!! GitHub does not offer rulesets for this repo on its current plan; see docs/GITHUB_SETUP.md" >&2
else
  cat "$tmp/err" >&2
  exit 1
fi

cat <<'NEXT'

Done. Remaining manual steps are in docs/GITHUB_SETUP.md (reviewer account, tokens, first CI run).
After the first CI run, confirm the required-check names in Settings -> Rules match the job names.
NEXT
