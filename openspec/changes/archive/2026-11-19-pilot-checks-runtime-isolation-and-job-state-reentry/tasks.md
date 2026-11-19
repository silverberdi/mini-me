## 1. Secure Bytecode Cache Isolation & Sandbox Mount (C04)

- [x] 1.1 In `src/minime/services/checks_runner.py`, implement secure private cache directory resolution: check `~/.cache/minime/pycache/<job_id>` or fallback to `tempfile.mkdtemp(prefix=f"minime_cache_{os.getuid()}_")`.
- [x] 1.2 Enforce fail-closed verification on the resolved cache directory: verify path is not a symlink, verify ownership matches process UID, and verify mode is restricted to `0700`.
- [x] 1.3 Prohibit `chown -R` or `chmod 1777` on shared directories and verify graceful handling of existing paths.
- [x] 1.4 In `src/minime/services/agent_confinement.py`, update `wrap_command()` to bind-mount only the validated dedicated bytecode cache path read-write (`--dir` and `--bind`) into Bubblewrap, prohibiting arbitrary unrestricted bind paths.

## 2. Claim-Fenced Job Error Transitions & Rollback Boundaries (C02)

- [x] 2.1 In `src/minime/services/execution_pipeline.py::run_checks_only()`, catch runner exceptions before outer fence check, re-validate recovery claim fence with row lock (`for_update=True`), transition `Job` to `CHECKS_FAILED` with sanitized error details, persist an `EvidenceDiagnostic`, and commit atomically.
- [x] 2.2 On claim fence loss (`StaleClaimError` or heartbeat failure), execute `uow.rollback()` and ensure ZERO database writes occur after fence loss.
- [x] 2.3 In `src/minime/services/orchestration_service.py::drive_coordinator()`, ensure consistent error recording and verify that coordinator stops `Run` in `NEEDS_HUMAN` alongside `Job` in `CHECKS_FAILED` under valid fence.

## 3. Proven Latest Environmental Fault Validation (C03)

- [x] 3.1 In `src/minime/services/recovery_convergence_service.py::_validate_checks_only_eligibility()`, validate latest pre-check failure from `Run.stop_details` (`CHECKS_ONLY_PIPELINE_EXCEPTION` with allowlisted exception type e.g. `PermissionError`) before `CheckResult` publication.
- [x] 3.2 Ensure fail-closed rejection of application code errors (e.g. `AssertionError`, `SyntaxError`, pytest failures) in latest execution batch and diagnostics.
- [x] 3.3 Re-verify candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced`, worktree porcelain cleanliness, base SHA, and valid repository binding.
- [x] 3.4 Require separate explicit human one-shot authorization before `recover_checks_only` admission.

## 4. Fresh Checks Batch Execution at RUNNING_CHECKS Replay Edge (C01, C05)

- [x] 4.1 In `src/minime/services/orchestration_service.py::drive_coordinator()`, implement checks-only execution replay edge at `RUNNING_CHECKS` stage when resuming an interrupted run without a passed batch.
- [x] 4.2 Invoke `pipeline.run_checks_only()` exactly once, record fresh `CheckResult` records with new timestamps bound to candidate generation, validate batch completeness, and freeze unchanged candidate.
- [x] 4.3 Stop run at `NEEDS_HUMAN` / `REVIEW_AUTHORIZATION_PENDING` without calling `execute_queued_job`, replaying OpenSpec APPLY, or dispatching AI models.

## 5. Adversarial PostgreSQL & Bubblewrap Verification Suite (C01–C05)

- [x] 5.1 Create test in `tests/test_pilot_checks_recovery_postgres.py` with two distinct simulated UIDs verifying that user B cannot be blocked by user A's preexisting cache files and that symlink/wrong-owner cache paths are rejected.
- [x] 5.2 Add test asserting that an unhandled runner exception atomically commits `Job` to `CHECKS_FAILED` and `Run` to `NEEDS_HUMAN` under claim fence, and that fence loss causes rollback with zero writes.
- [x] 5.3 Add test asserting that `RecoveryConvergenceService` admits an interrupted `RUNNING_CHECKS` / `NEEDS_HUMAN` run and executes exactly ONE fresh checks batch from `RUNNING_CHECKS`, validating the new results without model calls.
- [x] 5.4 Add negative adversarial tests verifying rejection if candidate SHA differs, worktree is dirty, claim is lost/superseded, or prior failure was an application code error.
- [x] 5.5 Execute disposable PostgreSQL and Bubblewrap test suite and produce deterministic verification report.
