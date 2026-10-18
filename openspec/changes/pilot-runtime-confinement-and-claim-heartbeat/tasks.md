## 1. Bubblewrap Unprivileged Virtual Devices

- [x] 1.1 In `src/minime/services/agent_confinement.py`, update `wrap_command()` on Linux to inject `["--dev", "/dev"]` into the Bubblewrap command array immediately following `["--ro-bind", "/", "/"]`.
- [x] 1.2 Add unit tests in `tests/test_agent_runtime_confinement.py` verifying `--dev /dev` presence in the generated Bubblewrap command tokens.
- [x] 1.3 Add deterministic execution test verifying that subprocesses inside the Bubblewrap sandbox can open `/dev/null` for reading and writing without `PermissionError` (Errno 13).
- [x] 1.4 Add real Linux Bubblewrap integration test executing `ChecksRunner` on a sample test suite asserting return code 0, standard device access, and clean stdout/stderr capture.
- [x] 1.5 Add real negative confinement test under Bubblewrap asserting that filesystem writes outside the assigned worktree (e.g. `/etc`, `/usr`, `/opt/minime/app`) fail with permission denied (EROFS or EACCES).

## 2. Explicit Heartbeat Ownership and Fencing Fail-Closed

- [x] 2.1 In `src/minime/services/orchestration_service.py`, update `drive_coordinator()` signature to accept `manage_heartbeat: bool = True`.
- [x] 2.2 In `drive_coordinator()`, when `manage_heartbeat=True` and `claim_context` is provided, instantiate and run `OperationalHeartbeat` with `lease_seconds=60` and `interval_seconds=15`, stopping and releasing the claim in a `finally` block.
- [x] 2.3 In `src/minime/services/recovery_convergence_service.py`, update coordinator invocation during recovery continuation to pass `manage_heartbeat=False`, preventing duplicate renewal threads and double-release races.
- [x] 2.4 In `drive_coordinator()`, implement strict fail-closed fencing: if `heartbeat.heartbeat_failed` is True or `validate_claim_context_authoritative()` fails, immediately raise `StaleClaimError`, roll back the session, and perform zero database writes (do not call `_stop_run()`, do not record `NEEDS_HUMAN`, do not release claim).
- [x] 2.5 Verify that `PostgresRecoveryClaimRepository.release_claim()` is strictly idempotent, safely returning `False` when releasing an already released, expired, or non-owned claim without exceptions.
- [x] 2.6 Add PostgreSQL integration test simulating a stage duration exceeding the base claim lease, asserting continuous lease renewal via `renew_claim_heartbeat_isolated` and successful CAS stage transition.
- [x] 2.7 Add PostgreSQL integration test simulating claim fence supersession, asserting that the stale worker raises `StaleClaimError`, rolls back the transaction, and commits zero mutations to the database.

## 3. Verification and OpenSpec Strict Validation

- [x] 3.1 Run targeted pytest suite verifying confinement, heartbeat ownership, and fail-closed fencing.
- [x] 3.2 Verify code formatting and linting with `ruff check` and `ruff format --check`.
- [x] 3.3 Run `openspec validate pilot-runtime-confinement-and-claim-heartbeat --strict --type change` and confirm clean validation.
