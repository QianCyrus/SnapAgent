# SnapAgent Agent Workflow

This repository uses a strict PR review loop. Follow these rules for every change.

## Branching And Isolation

- Always work on a feature branch via git worktree.
- Never develop directly on `release`.

## Mandatory PR Review Loop

For every PR, follow this cycle until there are no blocker findings:

1. Run local verification first (at least CI-equivalent tests).
2. Open/update the PR.
3. Spawn an independent subagent reviewer.
4. Require reviewer to post comments directly on GitHub PR.
5. Fix all blocker and important findings.
6. Spawn a new independent reviewer and repeat.
7. Merge only when:
   - reviewers report no blocker findings, and
   - CI is fully green.

## CI Failure Handling

If a merged PR causes `release` CI failure:

1. Pull failed run logs from GitHub Actions.
2. Identify exact failing test/case and root cause.
3. Create a minimal follow-up fix PR.
4. Re-run CI-equivalent tests locally.
5. Run the same independent review loop before merging fix PR.

## Command Surface Consistency

For slash-command changes, keep these in sync:

- command routing logic
- help text/menu registration (per channel)
- regression tests
