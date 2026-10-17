# GitHub setup (owner checklist)

These steps need your GitHub admin access, so an agent cannot do them. Do them once, before the
first agent task runs. About 10 minutes.

## 0. Repository visibility and plan

GitHub enforces branch rulesets server-side only on some plans:

| Repo | Plan | Branch rulesets / protection |
|---|---|---|
| Public | Free | Yes |
| Private | Free | **No** (the API returns "Upgrade to GitHub Pro or make this repository public") |
| Private | Pro / Team / Enterprise | Yes |

This project uses a **public repo on the Free plan**: rulesets cost nothing there, and a pre-commit
secret scan plus a full-history scan keep secrets out of a public history.

- Public means the code is world-readable. That is fine as long as no secret is ever committed (the
  pre-commit secret scan and the rules in AGENTS.md exist for this); ESPN cookies live only in
  environment variables.
- Private on the Free plan is possible but has no server-side enforcement: nothing stops a direct
  push to `main` or a merge that skips review. If you choose it, treat `main` as unprotected and
  watch it.

## 1. Create the repo and push the skeleton

1. Create the repo on GitHub (default branch `main`) and push the tooling files delivered with the
   specs: `.pre-commit-config.yaml`, `.github/`, `.opencode/`, `scripts/`, `docs/`.
2. Install the GitHub CLI (`gh`) and log in as **yourself**: `gh auth login`.

## 2. Apply repo settings

Run `scripts/setup-github.sh` (optionally pass `owner/repo`). It:

- enables squash and rebase merges (the ruleset requires linear history, so no merge commits), and
  deletes branches after merge;
- creates the `ready-for-review` label;
- makes the default Actions token read-only;
- creates a ruleset on `main` requiring a pull request and the CI checks `pre-commit`,
  `backend`, and `frontend`, with linear history and no force-push or deletion. It does **not**
  require an approval, because a human approves and merges every PR (see step 3). (If your plan
  does not allow a ruleset, the script says so and continues.)

Re-running it is safe.

## 3. Human approval and the independent reviewer

There is **no reviewer account and no token**. GitHub does not let an account approve its own pull
request, and agents never merge, so the roles are split:

- A separate **reviewer agent** reviews every ready PR with fresh eyes. `scripts/review.sh <pr>`
  runs `opencode run --agent reviewer` in a clean worktree at the PR head, with the reviewer
  definition taken from `main` (never from the PR). The reviewer posts its verdict as a review
  **comment** — never an approval — and lists what it verified.
- A **human reads the PR, the reviewer's report, and the CI result, then approves and merges**.
  Merge from the desktop app, with `gh pr merge <pr> --rebase` (or `--squash`), or with
  `scripts/merge.sh <pr>`
  (which also enforces the CI and governance gates). Merge governance changes yourself.

## 4. Author identity for agents

Agents push branches, open PRs, and post review comments as **you** (your `gh auth login`, or a
fine-grained token of your own with Contents: Write, Pull requests: Write, Metadata: Read, and
Checks: Read for this repo). There is no separate reviewer token to create or protect.

## 5. Agent environment

Each agent's environment (worktree) needs:

- `pre-commit install --hook-type pre-commit --hook-type pre-push` run in the worktree (hooks are
  per clone; for `git worktree` setups the hooks are shared via the main repo's `.git/hooks`, so
  install once in the main clone and verify it fires in a worktree);
- `gh`, `uv`, `pnpm`, and Node 26 installed and authenticated as above. The author agent pushes the
  branch with `scripts/ship.sh` and opens the draft PR itself through the GitHub MCP tools
  (`.opencode/pull-requests.md`); no hook pushes on commit.

## 6. First CI run, then verify

After the skeleton milestone lands and CI has run once:

1. **Settings -> Rules**: open the `main protection` ruleset and confirm each required check name
   matches a job that actually ran. If a name differs, edit the ruleset or
   `scripts/setup-github.sh`.
2. Open a test PR with a deliberate lint error: CI and pre-commit must fail.
3. Try `git push origin main` from a scratch clone: it must be rejected (ruleset).
4. Run the whole loop once on a trivial change: agent commit -> agent opens the draft PR ->
   `scripts/ship.sh --ready` -> `scripts/review.sh <n>` -> review the report yourself and merge
   (desktop, `gh pr merge`, or `scripts/merge.sh <n>`). Confirm a coverage comment appears on the
   PR and updates when you push again.

## 7. Day-to-day operation

- A PR gets the `ready-for-review` label when the author runs `scripts/ship.sh --ready`. Run
  `scripts/review.sh <pr>` then; it returns 0 when the reviewer found no blocking issues and 2 when
  it requested changes.
- A review exit code of 2 means changes requested: the author agent addresses them, pushes, and runs
  `scripts/ship.sh --ready` again; a brand-new review session follows. After 3 rounds the
  orchestrator stops and asks you.
- A human approves and merges every PR. PRs that touch rules, gates, or scripts (`AGENTS.md`, the
  specs, `.github/`, `.opencode/`, `scripts/`, `.pre-commit-config.yaml`) always need your review;
  merge them with `scripts/merge.sh <pr> --allow-governance`.

## Troubleshooting

- **`opencode run --agent` not recognized**: run `opencode run --help` and adjust
  `scripts/review.sh` to your installed version's flag for choosing an agent; the agent file lives
  at `.opencode/agents/reviewer.md`.
- **`review.sh` reports no parsable verdict**: the reviewer must post its review with
  `gh pr review <pr> --comment` and start the body with `Verdict: APPROVED` or
  `Verdict: CHANGES REQUESTED`.
- **`merge.sh` refuses**: it blocks a draft PR, failing or pending checks, or (without
  `--allow-governance`) a governance-file change.
- **Required check never reports**: the check name in the ruleset does not match the job name, or
  the workflow did not run for that PR.
