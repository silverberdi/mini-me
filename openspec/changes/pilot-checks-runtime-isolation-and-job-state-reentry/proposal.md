## Why

During the first authorized real production recovery of pilot N01 (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) on Ubuntu 192.168.0.194, `recover-checks` failed before running checks because `ChecksRunner` attempted to write bytecode cache to `/tmp/minime_pycache/<job-id>`, a shared host directory created by verification operator `silverman` with `0775` permissions, causing a `PermissionError: [Errno 13] Permission denied` when executed as service user `minime`. Furthermore, when the unhandled runner exception occurred, the coordinator stopped the `Run` into `RUNNING_CHECKS` / `NEEDS_HUMAN` (`is_active=false`), but left the associated `Job` trapped in `CHECKS_RUNNING` without a terminal status or error message, preventing legitimate subsequent re-entry under `RecoveryConvergenceService` without unsafe workarounds or model invocation.

In the current code, `RUNNING_CHECKS` only validates pre-existing check batches rather than running fresh checks. If an interrupted run in `RUNNING_CHECKS` / `NEEDS_HUMAN` is resumed with `checks_only=True`, the coordinator skips executing checks and immediately fail-closes with `INCOMPLETE_AUTHORITATIVE_CHECKS`.

This change delivers a robust, fail-closed runtime isolation for deterministic checks cache compatible with Ubuntu service users and Bubblewrap confinement, alongside transactional claim-fenced terminal state transition, execution of a fresh checks batch upon re-entry from `RUNNING_CHECKS`, and authoritative human-authorized re-entry for interrupted checks recovery.

## What Changes

- **Secure Cache Identity and Bubblewrap Mount (C04)**: Replace the predictable `/tmp/minime_pycache` path with a secure, private invocation/UID-scoped cache path (`~/.cache/minime/pycache/<job_id>` or verified non-predictable directory created via `mkdtemp` / `0700` no-follow verification). Strictly prohibit recursive `chown` or `chmod 1777` on shared directories. Mount read-write only this validated dedicated cache subtree inside Bubblewrap via `--dir` and `--bind`, with no unrestricted user-supplied extra bind paths.
- **Durable Job+Run Consistency Under Exceptions and Rollback (C02)**: Define strict transaction boundaries in `ExecutionPipelineService.run_checks_only` and `OrchestrationService.drive_coordinator`:
  - For non-fence runner exceptions (e.g. `PermissionError`, I/O failures), transactionally update `Job` to `CHECKS_FAILED` with sanitized diagnostics and stop `Run` in `is_active=false` / `NEEDS_HUMAN` under the valid recovery claim fence, ensuring no orphaned `CHECKS_RUNNING` jobs remain.
  - On claim/heartbeat fence loss (`StaleClaimError`), perform a complete rollback with ZERO subsequent database writes.
- **Proven Latest Pre-Check Environmental Failure (C03)**: Require `RecoveryConvergenceService._validate_checks_only_eligibility` to verify that the latest failure was a proven runner environmental fault (from `Run.stop_details` with code `CHECKS_ONLY_PIPELINE_EXCEPTION` and allowlisted exception types like `PermissionError`, or sandbox preflight failure, tied to the exact candidate SHA and generation) before CheckResult publication, strictly excluding application code or test errors. Require separate explicit human one-shot authorization before admission; eligibility alone does not authorize.
- **Re-Entry Replay Edge Executing Fresh Checks Batch at RUNNING_CHECKS (C01)**: Define an explicit claim-fenced checks-only replay edge for runs interrupted in `RUNNING_CHECKS` / `NEEDS_HUMAN` with `CHECKS_FAILED` (or interrupted `CHECKS_RUNNING`):
  - When authorized by human operator with valid claim fence, invoke `pipeline.run_checks_only()` exactly once to generate a FRESH complete batch of check results.
  - Bind the new results to the unchanged candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced` and current generation.
  - Validate only that new batch, freeze candidate, and stop at `NEEDS_HUMAN` / `REVIEW_AUTHORIZATION_PENDING`.
  - Strictly prohibit `execute_queued_job`, OpenSpec APPLY, model review/audit, or reuse of stale check batches.
- **One-Shot Governance and Adversarial Invariants (C05)**: Enforce monotonic claim fencing preventing concurrent or duplicate runs. On successful checks, stop at `REVIEW_AUTHORIZATION_PENDING` without invoking models. Reject dirty worktrees, mismatched candidate/base SHA, stale claims, and code errors.

## Capabilities

### Modified Capabilities
- `deterministic-checks-runner`: Define process-private / runtime-isolated bytecode cache requirements, symlink/ownership validation, and Bubblewrap sandbox bind mount guarantees for checks execution.
- `scheduler-and-recovery-convergence`: Define atomic claim-fenced terminal state transitions on checks pipeline errors, fresh batch execution on `RUNNING_CHECKS` re-entry, latest environmental fault validation, and one-shot human authorization governance.

## Impact

- `src/minime/services/checks_runner.py`: Update bytecode cache directory generation to use private user/job runtime path with no-follow verification, and ensure sandbox directory mounts.
- `src/minime/services/agent_confinement.py`: Ensure private checks cache directory is bound read-write into the sandbox when confinement is active, rejecting symlinks and unverified ownership.
- `src/minime/services/execution_pipeline.py`: In `run_checks_only`, wrap execution in proper error handling to transition `Job` to `CHECKS_FAILED` with claim validation on unhandled non-fence exceptions.
- `src/minime/services/orchestration_service.py`: In `drive_coordinator`, add explicit checks-only execution branch at `RUNNING_CHECKS` when resuming an interrupted checks run, transition `Job` coherently before/alongside `_stop_coordinator_run`, and enforce zero database writes on fence loss.
- `src/minime/services/recovery_convergence_service.py`: Update checks-only eligibility and recovery handler to admit runs in `RUNNING_CHECKS` / `NEEDS_HUMAN` with latest pre-check environmental fault evidence, and re-activate run under claim fence for fresh batch execution.
- `tests/test_pilot_checks_recovery_postgres.py`: Adversarial tests validating cache permissions under distinct real UIDs, Bubblewrap confinement, claim fencing, fresh batch execution from `RUNNING_CHECKS`, and zero model calls.
