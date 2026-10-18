## 1. Authoritative Preflight & Environmental Fault Gating

- [ ] 1.1 In `src/minime/services/recovery_convergence_service.py`, implement `_validate_checks_only_eligibility(run, job, worktree_path)` validating the full durable tuple (`run.run_id`, `job.id`, `project.project_id`, `run.change_name`, `run.base_sha == job.base_sha`, `job.candidate_sha`, `run.current_generation`, `git -C <worktree> rev-parse HEAD == job.candidate_sha`, clean working tree), characterizing pre-freeze candidate state without requiring nonexistent frozen rows.
- [ ] 1.2 In `src/minime/services/recovery_convergence_service.py`, implement exact diagnostic verification asserting that prior check failure diagnostics for this job and candidate contain proven runner environmental faults (`/dev/null` permission error or confinement preflight failure) and rejecting code-level errors.
- [ ] 1.3 In `src/minime/services/recovery_convergence_service.py`, implement `recover_checks_only(run_id, project_root, force=False)` with authoritative claim acquisition, single `OperationalHeartbeat` lease management, preflight gating, and fenced delegation passing `manage_heartbeat=False`.

## 2. Checks-Only Execution Pipeline & Manifest Materialization

- [ ] 2.1 In `src/minime/services/execution_pipeline.py`, implement `run_checks_only(job_id, candidate_generation, claim_context)` to validate worktree HEAD, materialize/persist `CandidateManifest` for the exact candidate SHA/base/generation, and transition `job.status = JobStatus.CHECKS_RUNNING`.
- [ ] 2.2 In `run_checks_only()`, execute `ChecksRunner.run(...)` under Bubblewrap on the preserved worktree, persisting candidate-bound check results and diagnostics.
- [ ] 2.3 In `run_checks_only()`, enforce single-batch completeness: require all configured checks in `project.checks` to execute and exit with 0 in the current execution batch before setting `JobStatus.CHECKS_PASSED`, setting `JobStatus.CHECKS_FAILED` if any check fails or is missing.

## 3. Coordinator Re-entry, Batch Consumption & Review Hold

- [ ] 3.1 In `src/minime/services/orchestration_service.py`, update `resume()` and `drive_coordinator()` signatures and control flow to accept `checks_only: bool = False`.
- [ ] 3.2 In `drive_coordinator()`, when `checks_only=True` and `job.status == JobStatus.CHECKS_FAILED`, transition directly to `RUNNING_CHECKS` and invoke `pipeline.run_checks_only()`, bypassing `pipeline.execute_queued_job()`.
- [ ] 3.3 In `drive_coordinator()`, consume verified check results, advance to `FREEZING_CANDIDATE`, materialize `OrchestrationCandidate` row from the verified manifest, and stop at review hold (`stop_outcome=NEEDS_HUMAN`, `human_gate=REVIEW_PENDING`) without dispatching reviewer or auditor models.

## 4. Operator CLI & Control-Plane Interface

- [ ] 4.1 In `src/minime/cli/main.py`, implement `minime orchestrate recover-checks <run_id>` calling `RecoveryConvergenceService.recover_checks_only()`.
- [ ] 4.2 In `src/minime/cli/main.py`, support `--checks-only` flag on `orchestrate resume` as an alias delegating to `recover_checks_only()`.

## 5. Disposable PostgreSQL & Worktree Functional E2E Tests

- [ ] 5.1 In `tests/test_pilot_checks_recovery_postgres.py`, add functional E2E test verifying happy-path checks-only recovery from the exact pilot checkpoint topology, asserting zero implementer calls, zero model inference, new check evidence persistence, candidate freezing, and clean halt at review hold.
- [ ] 5.2 In `tests/test_pilot_checks_recovery_postgres.py`, add negative tests for authority tuple mismatches (candidate SHA mismatch, base SHA mismatch, generation mismatch, worktree HEAD drift, dirty worktree).
- [ ] 5.3 In `tests/test_pilot_checks_recovery_postgres.py`, add negative test asserting rejection when prior failure diagnostics indicate a code assertion or compile error rather than a runner environmental fault.
- [ ] 5.4 In `tests/test_pilot_checks_recovery_postgres.py`, add negative tests for single-batch completeness, crash interruption, and non-inheritance of old check evidence.
- [ ] 5.5 In `tests/test_pilot_checks_recovery_postgres.py`, add negative tests for concurrency, lease expiry, claim fence supersession, and blocked-renewal teardown failure during checks-only recovery.
- [ ] 5.6 In `tests/test_pilot_checks_recovery_postgres.py`, add idempotency test verifying that repeated recovery invocations do not duplicate records or corrupt state.

## 6. Verification & Quality Gates

- [ ] 6.1 Run full targeted test suite verifying checks-only recovery under disposable PostgreSQL.
- [ ] 6.2 Verify code formatting and linting with `ruff check` and `ruff format --check`.
- [ ] 6.3 Run `openspec validate pilot-checks-only-checkpoint-recovery --strict --type change` and confirm clean validation.
