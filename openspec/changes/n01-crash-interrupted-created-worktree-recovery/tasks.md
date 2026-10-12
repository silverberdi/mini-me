## 1. Recovery authorization

- [x] 1.1 Add a CREATED-only predicate for an incomplete latest PREMATURE_STOP attempt while preserving existing environment/provider recovery outcomes.
- [x] 1.2 Require ordered, identity-bound JOB_INTERRUPTED, JOB_RECOVERED, and ORCHESTRATION_RECOVERED evidence after the attempt start, without mutating attempt or counter records.

## 2. PostgreSQL and Git regression coverage

- [x] 2.1 Add an isolated PostgreSQL and real-Git CONTINUE scenario proving the same Run/Job and CREATED worktree reach a diagnostic runner with attempt-count discrepancy and original B/snapshot/publication preserved.
- [x] 2.2 Add fail-closed coverage for missing/contradictory recovery evidence, finalized attempt, unauthorized Git state, candidate, and DELETED worktree.
- [x] 2.3 Run focused continuation tests (3 passed), adjacent worktree/restart recovery tests (31 passed), Ruff, strict OpenSpec validation, and `git diff --check`.
