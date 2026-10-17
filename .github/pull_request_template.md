<!-- Agent author: open and fill this in with the GitHub MCP tools; see .opencode/pull-requests.md. -->
## Summary

<!-- What does this PR change, and why? 2-5 sentences. -->

## Task and criteria

<!-- Task ID, and the acceptance criteria this PR satisfies, e.g. AC-VP-04, AC-VP-06 -->

## How it was verified

<!-- Commands run and their results; new/changed tests. The coverage report is posted by CI as a comment. -->

## Assumptions and open questions

<!-- Anything you had to assume. Link entries added to docs/OPEN_QUESTIONS.md. -->

## Author checklist

- [ ] Pre-commit hooks ran and passed (no `--no-verify`)
- [ ] New behavior has tests; no tests were deleted or loosened
- [ ] Coverage did not drop (see the CI coverage comment)
- [ ] Docs updated where behavior or setup changed (README, `.env.example`, `docs/openapi.json`)
- [ ] No secrets, credentials, or unrelated changes included
- [ ] Marked ready for review with `scripts/ship.sh --ready` only when everything above is true
