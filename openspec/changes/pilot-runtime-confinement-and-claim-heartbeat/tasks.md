## 1. Bubblewrap Standard Virtual Devices

- [ ] 1.1 In `src/minime/services/agent_confinement.py`, update `wrap_command()` on Linux to inject `["--dev", "/dev"]` into the Bubblewrap command array immediately following `["--ro-bind", "/", "/"]`.
- [ ] 1.2 Add unit tests in `tests/test_agent_runtime_confinement.py` verifying `--dev /dev` presence in the generated Bubblewrap command tokens.
- [ ] 1.3 Add deterministic execution test verifying that subprocesses inside the Bubblewrap sandbox can open `/dev/null` for reading and writing without `PermissionError` (Errno 13).
- [ ] 1.4 Add negative confinement test asserting that filesystem writes outside the assigned worktree (e.g. `/etc`, `/opt/minime/app`) remain strictly blocked under Bubblewrap with `/dev` mounted.

## 2. Orchestration Coordinator Operational Heartbeat

- [ ] 2.1 In `src/minime/services/orchestration_service.py`, wrap `drive_coordinator()` in an `OperationalHeartbeat` context manager when `claim_context` is provided and not already being renewed.
- [ ] 2.2 Add heartbeat deduplication logic in `drive_coordinator()` to prevent redundant renewal threads when called from an outer recovery context.
- [ ] 2.3 Implement fail-closed handling in `drive_coordinator()`: if `heartbeat.heartbeat_failed` is flagged, stop the coordinator immediately with `NEEDS_HUMAN` and preserve durable state without attempting CAS stage updates.
- [ ] 2.4 Add unit test in `tests/test_orchestration_service.py` verifying that an execution phase exceeding the claim lease duration maintains valid lease expiration via `renew_claim_heartbeat_isolated`.
- [ ] 2.5 Add unit test in `tests/test_orchestration_service.py` simulating heartbeat failure (lost lease or superseded fence token) and asserting fail-closed run preservation.

## 3. Verification and OpenSpec Strict Validation

- [ ] 3.1 Run targeted pytest suite verifying confinement and orchestration heartbeat changes.
- [ ] 3.2 Verify code formatting and linting with `ruff check` and `ruff format --check`.
- [ ] 3.3 Run `openspec validate pilot-runtime-confinement-and-claim-heartbeat --strict --type change` and confirm clean validation.
