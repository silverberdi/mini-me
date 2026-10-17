# Local admission and review-gate evidence — 2026-10-14

This is deterministic local evidence only. No provider, GitHub API, scheduler, production
service, or production database was invoked. It is not an E2E_PASS or delivery/deployment
evidence.

## Secure admission and bounded preflight

`SchedulerService.prepare_admission_evidence()` now evaluates the exact durable managed
repository binding and `ManagedWorkspaceGuard`'s pure `WORKTREE_CREATE` decision before
admission. It records the observed binding identity and resolved roots in immutable prepared
evidence. `evaluate_admission()` rejects a missing/invalid binding, denied workspace, or
binding changed after observation before Run/Job creation. The actual WorktreeManager still
rechecks the exact job destination before mutation. Configured implementer and reviewer must
also occur in the project's explicit provider allowlist. Existing readiness, provider health,
capacity, native-workflow/CLI preflight, continuation limits, and the separately reserved
OpenRouter drain budget remain authoritative; unknown/unavailable prerequisites wait or block
without inference.

`test_missing_managed_workspace_authority_blocks_before_admission`,
`test_managed_workspace_preflight_blocks_before_run_or_job_creation`,
`test_managed_workspace_preflight_accepts_exact_binding_and_denies_stale_binding`,
`test_managed_workspace_preflight_denies_wrong_remote_before_admission`,
`test_managed_workspace_preflight_denies_symlinked_repository_escape`,
`test_configured_provider_pair_must_be_explicitly_permitted_before_admission`,
`test_auth_required_preflight_waits_without_worktree_or_runner_invocation`, and
`test_duplicate_admission_refused_with_existing_run` cover missing binding, wrong root, stale
binding, wrong remote, symlink escape, provider-policy denial, auth-preflight denial, no Run/Job
creation on refusal, and duplicate admission. The legacy APPLY-attribution integration fixture
was corrected to stop fabricating a
`PUBLISHED` ownership with a sentinel SHA and no HEAD/event proof. Its local-only cases now run
without intake ownership; the predating-code case uses a real temporary bare remote whose main
ref remains at the pre-change commit. The shared disposable Git fixture now publishes its actual
`main` commit to that bare remote, allowing main-advancement reconciliation to observe remote
authority rather than relying on a local tracking ref.

## Review, preservation, and human gate

The primary complementary-review path remains distinct from the implementer and binds review
to the frozen candidate. `test_post_reassignment_capacity_check_uses_effective_executor`
proves a capacity-denied candidate remains at its exact SHA and neither reviewer nor audit runner
is invoked. A candidate-bound `AuditRecord`
does not satisfy review authority, and same-identity review is rejected. Existing acceptance
coverage reaches `READY_FOR_HUMAN_MERGE` and does not merge.

DeepSeek Direct as a reviewer is not implemented. The direct DeepSeek component is an auditor,
not a Review authority. Existing durable budget authorization is OpenRouter-specific and cannot
authorize a DeepSeek call. No audit record/result or OpenRouter budget was reused as review
evidence/authorization; task 4.3 remains open. A real Codex→AGY or DeepSeek review was not run.

## PostgreSQL migration and persistence check

An isolated, disposable local PostgreSQL 16 container was used. `alembic upgrade head` applied
migrations through `025_independent_audit_policy`; `alembic current` reported that revision as
the single head. A `PostgresPersistenceUnitOfWork` round-trip persisted and reloaded
`Project.independent_audit_required=True`, and a direct read returned `True`. The test container
was stopped and removed. No production database was accessed. Migration 025 is a backward-
compatible optional project audit-policy boolean; it does not create DeepSeek review authorization
or a distinct per-stage DeepSeek budget authority, and it does not need an additional table for
the currently implemented local contracts.

## Consolidated deterministic validation

```text
.venv/bin/python -m pytest -q \
  tests/test_native_openspec_apply.py \
  tests/test_execution_pipeline.py \
  tests/test_continuation_pipeline_integration.py \
  tests/test_orchestration_coordinator.py \
  tests/test_orchestration_acceptance.py \
  tests/test_mixed_authorship_review.py \
  tests/test_project_registry.py \
  tests/test_worktree_and_runner.py \
  tests/test_apply_attribution_gate.py \
  tests/test_scheduler_capacity_policy_convergence.py
131 passed in 104.73s
```

Additional focused preflight/review checks: `6 passed`; `tests/test_apply_attribution_gate.py`:
`12 passed`. Ruff check passed on changed Python files. The changed/new Python files touched in this
intervention pass Ruff formatting; six older files still fail whole-file format check on hunks
already present at the branch base, and were not wholesale reformatted. Change-level strict
OpenSpec validation and `git diff --check` pass. Repository-wide strict OpenSpec validation
currently reports `68 passed / 16 failed` for `autonomous-change-orchestration`,
`autonomous-delivery-loop`, `autonomous-post-merge-closure`, `complementary-reviewer-policy`,
`generic-provider-capacity-recovery-drain-policy`, `google-auth`,
`managed-repository-runtime-isolation`, `openspec-lifecycle-governance`, `openspec-readiness`,
`openspec-task-tracking`, `orchestration-driver-and-states`, `pipeline-diagnostic-summary`,
`pr-preparation-and-recovery`, `provider-efficiency-and-anti-loop`,
`reviewer-independence-and-telemetry`, and `telemetry-summary`. This run did not compare that
failure set to a clean base worktree and does not claim baseline equivalence.

No full pytest suite, real-provider E2E, GitHub fixture, DeepSeek request, deployment, or scheduler
activation was performed.
