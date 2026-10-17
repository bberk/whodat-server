# GitHub setup (owner checklist)

These steps need your GitHub admin access and accounts, so they cannot be done by agents. Do them once, before the first agent task runs. About 20 minutes.

## 0. Decide repository visibility and plan

GitHub only enforces branch rules server-side in some situations:

| Repo | Plan | Branch rulesets / protection |
|---|---|---|
| Public | Free | Yes |
| Private | Free | **No** (the API returns "Upgrade to GitHub Pro or make this repository public") |
| Private | Pro / Team / Enterprise | Yes |

- **Public repo, or a paid plan**: everything below is enforced by GitHub itself, in addition to the checks in `scripts/merge.sh`. Recommended.
- **Private repo on the Free plan**: the workflow still functions, but only because agents and `scripts/merge.sh` follow the rules. Nothing stops a direct push to `main` or a merge that skips review. If you stay here, treat `main` as unprotected and watch it.
- Public means the code is world-readable. That is fine as long as no secret is ever committed (the pre-commit secret scan and the rules in AGENTS.md exist for this); ESPN cookies live only in environment variables.

## 1. Create the repo and push the skeleton

1. Create the repo on GitHub (default branch `main`) and push the four spec documents plus the tooling files delivered with them: `.pre-commit-config.yaml`, `.github/`, `.opencode/`, `scripts/`, `docs/`.
2. Install the GitHub CLI (`gh`) and log in as **yourself**: `gh auth login`.

## 2. Apply repo settings

Run `scripts/setup-github.sh` (optionally pass `owner/repo`). It:

- enables squash merge only, and deletes branches after merge;
- creates the `ready-for-review` label;
- makes the default Actions token read-only;
- creates a ruleset on `main` requiring: a pull request, 1 approval from someone other than the author, stale approvals dismissed on new pushes, the CI checks `pre-commit`, `backend (sqlite)`, `backend (postgres)`, `frontend`, linear history, and no force-push or deletion. (If your plan does not allow it, the script says so and continues.)

Re-running it is safe.

## 3. Create the reviewer identity

GitHub does not let an account approve its own pull request, so the reviewer agent needs a **second GitHub account**.

1. Create a free GitHub account for the reviewer (for example `yourname-reviewer-bot`). GitHub's terms allow one machine account per person; keep it clearly labeled as a bot.
2. Invite it to the repo as a collaborator with **Write** access, and accept the invitation while logged in as that account. (Write is needed for it to count as an approving reviewer.)
3. Logged in as the reviewer account, create a **fine-grained personal access token** limited to this one repository with:
   - Contents: Read
   - Pull requests: Read and write
   - Commit statuses: Read
   - Checks: Read
   - Metadata: Read (automatic)
   Give it a short expiry and calendar a renewal.
4. Give that token to the orchestrator as the environment variable `REVIEWER_GH_TOKEN`. Never put it in the repo.

## 4. Author identity for agents

Agents push branches and open PRs as **you** (your `gh auth login`, or a fine-grained token of your own with Contents: Write, Pull requests: Write, Metadata: Read, and Checks: Read for this repo). Never give agents the reviewer token, and never give the reviewer your token.

## 5. Agent environment

Each agent's environment (worktree) needs:

- `pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type post-commit` run in the worktree (hooks are per clone; for `git worktree` setups the hooks are shared via the main repo's `.git/hooks`, so install once in the main clone and verify it fires in a worktree);
- `AGENT_AUTOSHIP=1` so commits push the branch and open a draft PR (human commits are unaffected);
- `gh`, `uv`, `pnpm`, and Node 26 installed and authenticated as above.

## 6. First CI run, then verify

After the skeleton milestone lands and CI has run once:

1. **Settings -> Rules**: open the `main protection` ruleset and confirm each required check name matches a job that actually ran. If a name differs, edit the ruleset or `scripts/setup-github.sh`.
2. Open a test PR with a deliberate lint error: CI and pre-commit must fail.
3. Try `git push origin main` from a scratch clone: it must be rejected (ruleset). Skip this if you chose the private/Free option.
4. Run the whole loop once on a trivial change: agent commit -> draft PR -> `scripts/ship.sh --ready` -> `scripts/review.sh <n>` -> `scripts/merge.sh <n>`. Confirm a coverage comment appears on the PR and updates when you push again.

## 7. Day-to-day operation

- The orchestrator runs `scripts/review.sh <pr>` when a PR gets the `ready-for-review` label (or when the author agent reports the task done), then `scripts/merge.sh <pr>` if the review exits 0.
- A review exit code of 2 means changes requested: the author agent addresses them, pushes, and runs `scripts/ship.sh --ready` again; a brand-new review session follows. After 3 rounds the orchestrator stops and asks you.
- PRs that touch rules, gates, or scripts (`AGENTS.md`, the specs, `.github/`, `.opencode/`, `scripts/`, `.pre-commit-config.yaml`) are never auto-approved or auto-merged. Review them yourself, then merge with `scripts/merge.sh <pr> --allow-governance`.

## Troubleshooting

- **`opencode run --agent` not recognized**: run `opencode run --help` and adjust `scripts/review.sh` to your installed version's flag for choosing an agent; the agent file lives at `.opencode/agents/reviewer.md`.
- **Reviewer cannot approve**: it is probably the same account as the PR author, or lacks Write access; `scripts/review.sh` checks the first of these.
- **`merge.sh` says no current approval**: new commits were pushed after the review; run the review again.
- **Required check never reports**: the check name in the ruleset does not match the job name, or the workflow did not run for that PR.
