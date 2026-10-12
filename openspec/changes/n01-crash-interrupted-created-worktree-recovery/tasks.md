## 1. Recovery authorization

- [x] 1.1 Add a CREATED-only predicate for an incomplete latest PREMATURE_STOP attempt while preserving existing environment/provider recovery outcomes.
- [x] 1.2 Require the latest identity-bound JOB_RECOVERED from canonical Control Plane continuation after the attempt start, without mutating attempt or counter records; do not require startup-only events.

## 2. PostgreSQL and Git regression coverage

- [x] 2.1 Add an isolated PostgreSQL and real-Git CONTINUE scenario proving the same Run/Job and CREATED worktree reach a diagnostic runner with attempt-count discrepancy and original B/snapshot/publication preserved.
- [x] 2.2 Add fail-closed coverage for absent, stale, and contradictory recovery evidence, finalized attempt, pending external action, unauthorized Git state, candidate, and DELETED worktree.
- [x] 2.3 Run focused PostgreSQL/Git continuation tests (10 passed), adjacent worktree/restart recovery tests (31 passed), Ruff, strict OpenSpec validation, and `git diff --check`.
