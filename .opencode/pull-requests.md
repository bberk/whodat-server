# Opening and filling out a pull request

You author the branch, and a **human** reads the description before deciding whether to merge. Write
it as a factual case for the change: no requests, no instructions to the reviewer, no marketing.
`scripts/ship.sh` only pushes the branch — **you open the pull request yourself** with the GitHub
MCP tools.

## Open it early, as a draft

Once your branch has a commit (the `ship` hook pushes it when `AGENT_AUTOSHIP=1`; otherwise run
`scripts/ship.sh` yourself), open a **draft** PR:

```
tools.github.create_pull_request({
  owner: "bberk",
  repo: "whodat-server",
  base: "main",
  head: "agent/<task-id>-<slug>",
  title: "<imperative summary, about 50 characters, no trailing period>",
  body: "<the filled-in body described below>",
  draft: true,
})
```

A draft PR is never reviewed or merged, so opening it before the work is finished is safe and
useful: CI runs and the work is visible. Keep committing to the same branch and do not open a second
PR. Update the description with `tools.github.update_pull_request` (`owner`, `repo`, `pullNumber`,
and the new `body`) whenever the scope changes — never leave stale text.

### When the GitHub MCP tools are unavailable

The MCP server is the preferred path, but it needs valid credentials. If a `tools.github.*` call
fails — the server has been seen to answer `401 token authentication failed` — fall back to `gh`,
which is authenticated in the agent environment:

```bash
gh pr create --draft --base main --head "agent/<task-id>-<slug>" \
  --title "<imperative summary>" --body-file <file>
gh pr edit <pr-number> --body-file <file>   # later updates
```

Tell the orchestrator that the MCP call failed instead of switching silently, so the credentials
get fixed; AC-WF-22 accepts either path.

## Fill in the body

Start from `.github/pull_request_template.md` and fill every section. Keep the checklist boxes and
tick only the ones that are true.

- **Summary** — what changes and why, 2-5 sentences. Say what a reader will see in the diff.
- **Task and criteria** — the task ID and the acceptance criteria this PR satisfies, by their IDs
  (`AC-VP-04`). Name any criterion you claim but have not met, and say why.
- **How it was verified** — the exact commands you ran and what they printed, plus the tests you
  added or changed. Never claim a result you did not observe. Quote coverage numbers from the CI
  comment, not from memory.
- **Assumptions and open questions** — what you assumed, and any entry you added to
  `docs/OPEN_QUESTIONS.md`. If you deviated from a document, or a document overstates what exists,
  say so here.
- **Author checklist** — tick the boxes that hold; leave the last one until the PR is ready.

## Title

The title becomes the squash-merge commit subject, so it follows the commit rules: imperative mood,
about 50 characters, no trailing period, no ticket noise. `Add tie-splitting for lowest score`, not
`VP fixes (WIP)`.

## Finish

1. Rebase on `main` and re-read the body against the final diff; fix anything stale.
2. Run `scripts/ship.sh --ready`. It pushes, marks the PR ready, and adds the `ready-for-review`
   label (GitHub labels are not available over MCP), which is the orchestrator's cue to start a
   review.
3. Address a `changes requested` review by fixing, committing, and running `scripts/ship.sh --ready`
   again; a new reviewer session starts from scratch.

Do not put anything addressed to the reviewer in the PR: the reviewer treats PR text as untrusted
data. Everything it needs is a fact about the change.
