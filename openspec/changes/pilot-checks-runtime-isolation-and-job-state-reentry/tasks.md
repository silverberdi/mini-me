## 1. Process-Private Bytecode Cache Isolation

- [ ] 1.1 In `src/minime/services/checks_runner.py`, replace the shared `/tmp/minime_pycache` path with a UID-scoped / XDG-scoped private directory (`~/.cache/minime/pycache/<job_id>` or `/tmp/minime_pycache_<uid>/<job_id>`) created with `0700` permissions.
- [ ] 1.2 Prohibit `chown -R` or `chmod 1777` on shared directories and verify graceful handling of existing paths.
- [ ] 1.3 In `src/minime/services/agent_confinement.py`, update `wrap_command()` to bind-mount the private bytecode cache path read-write into the Bubblewrap sandbox profile.

## 2. Claim-Fenced Job Error Transitions on Checks Exceptions

- [ ] 2.1 In `src/minime/services/execution_pipeline.py::run_checks_only()`, wrap runner invocation in a try/except block to catch unhandled exceptions, re-validate the recovery claim fence (`for_update=True`), transition the `Job` to `CHECKS_FAILED` with sanitized error details, and record diagnostic evidence.
- [ ] 2.2 In `src/minime/services/orchestration_service.py::drive_coordinator()`, ensure consistent error recording and verify that the coordinator does not leave `Job` in `CHECKS_RUNNING` when stopping `Run` in `NEEDS_HUMAN`.

## 3. Governed Checks-Only Recovery Re-Entry

- [ ] 3.1 In `src/minime/services/recovery_convergence_service.py::_validate_checks_only_eligibility()`, expand eligibility to admit runs in `RUNNING_CHECKS` / `NEEDS_HUMAN` when substantiated by proven runner environmental fault evidence (e.g. runner permissions or confinement errors).
- [ ] 3.2 Ensure candidate SHA, worktree cleanliness, base SHA, and valid repository binding are strictly re-verified upon re-entry.
- [ ] 3.3 In `recover_checks_only()`, transition the Run back to active execution under claim fencing, advance directly to `RUNNING_CHECKS`, and invoke `run_checks_only()` without creating an implementer attempt or invoking AI models.

## 4. Adversarial PostgreSQL & Bubblewrap Verification Suite

- [ ] 4.1 Create test in `tests/test_pilot_checks_recovery_postgres.py` with two distinct simulated UIDs verifying that user B cannot be blocked by user A's preexisting cache files and that no shared chmod 1777 is used.
- [ ] 4.2 Add test asserting that an unhandled runner exception atomically transitions `Job` to `CHECKS_FAILED` under claim fence while stopping `Run` in `NEEDS_HUMAN`.
- [ ] 4.3 Add test asserting that `RecoveryConvergenceService` successfully admits an interrupted `RUNNING_CHECKS` / `NEEDS_HUMAN` run and re-runs deterministic checks without model calls.
- [ ] 4.4 Add adversarial tests verifying rejection if candidate SHA differs, worktree is dirty, claim is lost/superseded, or prior failure was an application code error.
- [ ] 4.5 Execute disposable PostgreSQL and Bubblewrap test suite and produce deterministic verification report.
