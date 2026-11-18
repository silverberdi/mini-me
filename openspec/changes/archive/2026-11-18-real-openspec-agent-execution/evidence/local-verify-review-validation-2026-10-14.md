# Local VERIFY and review validation — 2026-10-14

This is local deterministic evidence only. No provider, GitHub API, scheduler, production service,
or production database was invoked. It is not an E2E_PASS or delivery/deployment evidence.

## Candidate-tree VERIFY authority

`OrchestrationService._evaluate_verify_gate()` now requires the active Job and frozen Candidate,
loads the durable worktree ownership, resolves the canonical Job worktree through
`WorktreeManager`, and calls the existing frozen-candidate adoption verifier before evaluating
OpenSpec or changed paths. That verifier binds Run/Job/project/change, CREATED ownership/path,
base SHA, candidate SHA/generation/ref, candidate manifest and completed attempt, unresolved
external actions, clean Git state, and ancestry. Any failure returns VERIFY_UNKNOWN and blocks the
human-merge path. Both `VerifyGate` and `git diff base..candidate` now use that exact verified
candidate worktree rather than the mutable managed checkout.

`test_candidate_changed_paths_are_read_from_candidate_worktree` creates a real temporary Git
worktree and proves its candidate-only file is the observed path. The orchestration acceptance
tests exercise the frozen candidate through checks, review, VERIFY, and the human-only PR gate.
Existing candidate-adoption tests reject entering candidate-free recovery when a frozen candidate
exists. The native apply resolver is a pure identity/workflow resolver; it has no readiness or
admission mutation authority, and missing native skill preflight blocks before runner invocation.

## Independent review authority

`test_review_authority_fail_closed_validation` now additionally submits a candidate-bound,
structured `READY_TO_MERGE` response labeled with the implementer identity and confirms it is
rejected. The same test retains missing/stale candidate SHA and base SHA rejection and verifies the
exact current review binding. `test_mixed_authorship_review.py` and project registry tests cover
surviving-file attribution and invalid same-provider role pairing.

DeepSeek review dispatch is intentionally not claimed as implemented. The repository has a direct
DeepSeek auditor, but that authority and its `AuditRecord` cannot be promoted into review evidence.
The current durable pricing/budget authority is OpenRouter-specific and there is no candidate-bound
per-stage DeepSeek review authorization/charge reservation. Reusing either would falsely imply
direct-provider budget authorization. Therefore task 4.3 remains open and no DeepSeek call was made.

## Validation

Consolidated relevant local suites:

```text
.venv/bin/python -m pytest -q \
  tests/test_native_openspec_apply.py \
  tests/test_execution_pipeline.py \
  tests/test_continuation_pipeline_integration.py \
  tests/test_orchestration_coordinator.py \
  tests/test_orchestration_acceptance.py \
  tests/test_mixed_authorship_review.py \
  tests/test_project_registry.py \
  tests/test_worktree_and_runner.py
86 passed in 55.02s
```

Static validation:

```text
ruff check <changed Python files>: All checks passed
ruff format --check <new Python module, test module, migration>: 3 files already formatted
openspec validate real-openspec-agent-execution --strict: Change is valid
git diff --check: passed
alembic heads: 025_independent_audit_policy (single head)
```

Legacy files touched by this change have repository-baseline formatting differences; they were not
reformatted wholesale to avoid unrelated diff churn. The newly created Python module, test module,
and migration pass Ruff formatting.
