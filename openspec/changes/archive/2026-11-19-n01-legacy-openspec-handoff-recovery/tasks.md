## 1. Recovery lineage and CREATED adoption

- [x] 1.1 Reuse authoritative recovery validation for DELETED recreation and CREATED existing-worktree adoption while preserving source base B.
- [x] 1.2 Reject identity, path, Git registration, marker, branch, snapshot event, candidate, and base ancestry contradictions.

## 2. Published artifact repair

- [x] 2.1 Validate the exact published manifest and remote SHA, then preflight every file for exact bytes or one omitted final LF.
- [x] 2.2 Restore exact published blobs idempotently and persist redacted durable repair evidence.
- [x] 2.3 Add adversarial rejection tests for other byte changes, paths, ownership, publication, snapshot, candidate, and divergence.

## 3. End-to-end continuation and validation

- [x] 3.1 Add isolated PostgreSQL + real Git test for FAILED first CONTINUE, CREATED retry, same Run/Job, LF repair and confined diagnostic runner.
- [x] 3.2 Preserve DELETED B→C continuation and existing sandbox/confined-runner regressions.
- [x] 3.3 Run focused tests (34 passed, 2 skipped); Ruff check and format passed; strict OpenSpec validation and `git diff --check` passed. The four adjacent `test_execution_pipeline.py` failures were reproduced unchanged on clean base `88c018e413b3e7cc7af0766cdf1a1be4fd0003b5`.
