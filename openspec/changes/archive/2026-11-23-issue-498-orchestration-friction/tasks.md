## 1. Native Explore and Propose evidence

- [x] 1.1 Replace exact Explore success-token gating with process/output evidence while preserving native human questions and actionable failure reasons.
- [x] 1.2 Remove required model-authored completion-token dependence where native Propose artifacts and strict OpenSpec CLI validation establish the result; retain fail-closed checks for missing or invalid artifacts.
- [x] 1.3 Add focused regressions for successful Explore without the exact phrase, genuine human-required output, failed/empty execution, and invalid Propose artifacts.

## 2. Recovery and Apply re-entry

- [x] 2.1 Route missing recovery authorization through the existing gate/API/UI contract with the concrete prerequisite and authorized operator action; cover cases with no safe action.
- [x] 2.2 Allow verified review corrections to authorize Apply re-entry on the same Run, Change, branch, worktree, and candidate while retaining existing invocation, retry, budget, and regression guards.
- [x] 2.3 Add focused regressions proving corrected re-entry proceeds and identity changes or unresolved human authorization still block.

## 3. Reviewer input and transport

- [x] 3.1 Identify the actual failure mode for large review prompts; use the release workflow's `src/minime/static` rebuild from `frontend/dist` as evidence and fixed Git pathspec exclusions to bound command arguments while retaining authored frontend sources.
- [x] 3.2 Keep large prompts out of process arguments using the configured transport and preserve review coverage when provider context requires partitioning; report any incomplete coverage explicitly.
- [x] 3.3 Add tests for the specified build-output exclusions, authored frontend source retention, transport selection, bounded partitioning, and no silent truncation.

## 4. GitHub merge response handling

- [x] 4.1 Read back the same PR after HTTP 405 and distinguish unknown/transient mergeability from confirmed conflict, failed checks, or branch-protection denial.
- [x] 4.2 Retry only an unknown/transient state with bounded backoff and retain typed diagnostics for permanent or exhausted outcomes.
- [x] 4.3 Add adapter/coordinator tests for transient retry, bounded exhaustion, permanent rejection, and preservation of PR/worktree state.

## 5. Candidate verification and deployed-Run acceptance

- [x] 5.1 Run the focused automated regressions for Explore-to-Propose, recovery-to-Apply, review input, and PR-merge handling; report skipped test targets explicitly and do not claim synthetic fixtures as remote GitHub E2E evidence.
- [x] 5.2 Confirm Issue #489-owned autonomy/time metrics are unchanged and no new state machine, queue, database entity, workflow substitute, or deployment responsibility was introduced.
- [x] 5.3 Run the applicable project checks and native OpenSpec Verify against the committed candidate SHA; record `tests/test_e2e_isolated_fixture.py` (two skipped synthetic cases, not remote E2E evidence) and the real deployed-Run acceptance as pending until each has observable evidence, not as passed.
