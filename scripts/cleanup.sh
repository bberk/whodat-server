#!/usr/bin/env bash
# Delete local branches whose pull request is already merged, and remove the worktrees they are
# checked out in. GitHub deletes the remote branch on merge, but not the author's local one, and a
# merge made in the web UI never runs a local script at all — this is the step that finishes the job.
#
# Usage: scripts/cleanup.sh [--dry-run] [branch ...]
#
# With no branch arguments it considers every local `agent/*` branch. A branch is removed only when
# every condition below holds, so nothing in flight is lost:
#   - it is not `main`/`master`, and it is not the branch checked out in the current directory
#     (run `git checkout main && git pull` first when that is the branch you just had merged);
#   - GitHub reports a merged pull request for it;
#   - its local head is exactly the commit that pull request merged (no commits after the merge);
#   - when another worktree has it checked out, that worktree has no uncommitted or untracked
#     changes (a dirty worktree is reported and kept).
#
# Commits that were never pushed are not a separate case: if the branch moved past the merged PR
# head, the third condition already keeps it.
#
# Requires: git, gh (authenticated with read access), jq.
set -euo pipefail

usage() {
  echo "usage: scripts/cleanup.sh [--dry-run] [branch ...]" >&2
}

dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    -h | --help) usage; exit 0 ;;
    -*) echo "cleanup.sh: unknown option '$1'" >&2; usage; exit 64 ;;
    *) break ;;
  esac
done

for tool in git gh jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "cleanup.sh: '$tool' is required" >&2; exit 1; }
done

current="$(git rev-parse --abbrev-ref HEAD)"
git fetch --prune --quiet origin 2>/dev/null || true

# Print the path of the worktree that has <branch> checked out, if any.
worktree_for() {
  local want="refs/heads/$1" path="" line
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) path="${line#worktree }" ;;
      "branch "*)
        if [[ "${line#branch }" == "$want" ]]; then
          printf '%s\n' "$path"
          return 0
        fi
        ;;
    esac
  done < <(git worktree list --porcelain)
  return 1
}

clean() {
  local branch="$1" pr head local_head path

  case "$branch" in
    main | master)
      echo "cleanup.sh: $branch: protected branch, keeping"
      return 0
      ;;
  esac
  if [[ "$branch" == "$current" ]]; then
    echo "cleanup.sh: $branch: checked out here, keeping."
    echo "            switch away first (git checkout main && git pull) and re-run."
    return 0
  fi
  if ! git show-ref --verify --quiet "refs/heads/$branch"; then
    echo "cleanup.sh: $branch: no such local branch"
    return 0
  fi

  if ! pr="$(gh pr list --head "$branch" --state merged --limit 1 \
    --json number,headRefOid,url 2>/dev/null)"; then
    echo "cleanup.sh: $branch: could not query GitHub, keeping" >&2
    return 0
  fi
  if [[ -z "$pr" || "$(jq 'length' <<<"$pr")" -eq 0 ]]; then
    echo "cleanup.sh: $branch: no merged pull request, keeping"
    return 0
  fi

  head="$(jq -r '.[0].headRefOid' <<<"$pr")"
  local_head="$(git rev-parse "refs/heads/$branch")"
  if [[ "$local_head" != "$head" ]]; then
    echo "cleanup.sh: $branch: has commits the merge did not include, keeping" >&2
    return 0
  fi

  if path="$(worktree_for "$branch")"; then
    if [[ "$dry_run" -eq 1 ]]; then
      echo "cleanup.sh: would remove worktree $path and delete $branch"
      return 0
    fi
    if ! git worktree remove "$path"; then
      echo "cleanup.sh: $branch: worktree $path has changes, keeping" >&2
      return 0
    fi
  fi

  if [[ "$dry_run" -eq 1 ]]; then
    echo "cleanup.sh: would delete $branch"
    return 0
  fi
  git branch -D "$branch" >/dev/null
  echo "cleanup.sh: deleted $branch ($(jq -r '.[0].url' <<<"$pr"))"
}

if [[ $# -gt 0 ]]; then
  while [[ $# -gt 0 ]]; do
    clean "$1"
    shift
  done
else
  while IFS= read -r branch; do
    clean "$branch"
  done < <(git for-each-ref --format='%(refname:short)' refs/heads/agent)
fi
