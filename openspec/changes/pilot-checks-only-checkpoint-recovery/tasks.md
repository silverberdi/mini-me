## 1. Authority & Environmental Fault Gating

- [ ] 1.1 In `src/minime/services/recovery_convergence_service.py`, implement `_validate_checks_only_eligibility(run, job, worktree_path)` validating the full durable tuple (`run_id`, `job_id`, `project_id`, `change_name`, `base_sha`, `candidate_sha`, `current_generation`, and worktree git `HEAD`).
- [ ] 1.2 In `src/minime/services/recovery_convergence_service.py`, implement environmental fault evidence verification asserting that historical `evidence_diagnostics` or `check_results` contain proven runner faults (`/dev/null` permission error or confinement preflight failure) and rejecting code-level errors.
- [ ] 1.3 In `src/minime/services/recovery_convergence_service.py`, implement `recover_checks_only(run_id, project_root, force=False)` with authoritative claim acquisition, `OperationalHeartbeat` lease management, preflight gating, and fenced execution.

## 2. Checks-Only Coordinator Execution Flow

- [ ] 2.1 In `src/minime/services/orchestration_service.py`, update `resume()` and `drive_coordinator()` signatures and control flow to accept `checks_only: bool = False`.
- [ ] 2.2 In `drive_coordinator()`, when `checks_only=True` and `job.status == JobStatus.CHECKS_FAILED`, bypass `pipeline.execute_queued_job()` and transition directly to `RUNNING_CHECKS`.
- [ ] 2.3 In `drive_coordinator()`, execute deterministic checks on the preserved worktree, updating `job.status` to `CHECKS_PASSED` on success and advancing to `FREEZING_CANDIDATE` and `COMPLEMENTARY_REVIEW`.
- [ ] 2.4 In `drive_coordinator()`, handle check failure fail-closed by persisting fresh diagnostic evidence, maintaining `CHECKS_FAILED`, and stopping at `NEEDS_HUMAN` without looping.

## 3. Operator CLI & Control-Plane Interface

- [ ] 3.1 In `src/minime/cli/main.py`, implement `minime orchestrate recover-checks <run_id>` calling `RecoveryConvergenceService.recover_checks_only()`.
- [ ] 3.2 In `src/minime/cli/main.py`, support `--checks-only` flag on `orchestrate resume` as an alias delegating to `recover_checks_only()`.

## 4. Disposable PostgreSQL & Worktree Functional E2E Tests

- [ ] 4.1 In `tests/test_pilot_checks_recovery_postgres.py`, add functional E2E test verifying happy-path checks-only recovery from the exact pilot checkpoint topology, asserting zero implementer calls, zero model inference, new check evidence persistence, and advance to candidate freezing.
- [ ] 4.2 In `tests/test_pilot_checks_recovery_postgres.py`, add negative tests for tuple mismatches (candidate SHA mismatch, base SHA mismatch, generation mismatch, worktree HEAD drift).
- [ ] 4.3 In `tests/test_pilot_checks_recovery_postgres.py`, add negative test asserting rejection when prior failure is a regular code assertion rather than an environmental sandbox fault.
- [ ] 4.4 In `tests/test_pilot_checks_recovery_postgres.py`, add negative tests for concurrency, lease expiry, and claim fence supersession during checks-only recovery.
- [ ] 4.5 In `tests/test_pilot_checks_recovery_postgres.py`, add idempotency test verifying that repeated recovery invocations do not duplicate records or corrupt state.

## 5. Verification & Quality Gates

- [ ] 5.1 Run full targeted test suite verifying checks-only recovery under disposable PostgreSQL.
- [ ] 5.2 Verify code formatting and linting with `ruff check` and `ruff format --check`.
- [ ] 5.3 Run `openspec validate pilot-checks-only-checkpoint-recovery --strict --type change` and confirm clean validation.
