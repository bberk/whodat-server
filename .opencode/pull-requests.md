# Opening and filling out a pull request

You author the branch, and a **human** reads the description before deciding whether to merge. Write
it as a factual case for the change: no requests, no instructions to the reviewer, no marketing.
`scripts/ship.sh` only pushes the branch — **you open the pull request yourself** with `gh`,
running as the App identity through `scripts/bot-identity.sh run` (never a bare `gh`, which would
act as the owner).

## Open it early, as a draft

Push your branch first with `scripts/ship.sh` (nothing pushes on commit). Write the body to a file
outside the repository (for example under `$TMPDIR`), then open a **draft** PR:

```bash
scripts/bot-identity.sh run gh pr create --draft --base main \
  --head "agent/<task-id>-<slug>" \
  --title "<imperative summary, about 50 characters, no trailing period>" \
  --body-file "$TMPDIR/pr-body.md"
```

A draft PR is never reviewed or merged, so opening it before the work is finished is safe and
useful: CI runs and the work is visible. Keep committing to the same branch and do not open a second
PR. Update the description whenever the scope changes — never leave stale text:

```bash
scripts/bot-identity.sh run gh pr edit <pr-number> --body-file "$TMPDIR/pr-body.md"
```

Find the PR later with `scripts/bot-identity.sh run gh pr view <branch> --json url,number`. If `gh`
fails with an authentication error, stop and tell the orchestrator; do not fall back to your own
credentials.

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

The title follows the commit rules — imperative mood, about 50 characters, no trailing period, no
ticket noise. It is what appears in `git log`, and it becomes the commit subject when a PR is
squash-merged. `Add tie-splitting for lowest score`, not `VP fixes (WIP)`.

## Finish

1. Rebase on `main` and re-read the body against the final diff; fix anything stale.
2. Run `scripts/ship.sh --ready`. It pushes, marks the PR ready, and adds the `ready-for-review`
   label, which is the orchestrator's cue to start a review.
3. Address a `changes requested` review by fixing, committing, and running `scripts/ship.sh --ready`
   again; a new reviewer session starts from scratch.

Do not put anything addressed to the reviewer in the PR: the reviewer treats PR text as untrusted
data. Everything it needs is a fact about the change.
