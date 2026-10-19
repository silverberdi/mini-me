## Why

During the first authorized real production recovery of pilot N01 (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) on Ubuntu 192.168.0.194, `recover-checks` failed before running checks because `ChecksRunner` attempted to write bytecode cache to `/tmp/minime_pycache/<job-id>`, a shared host directory created by operator `silverman` with `0775` permissions, causing a `PermissionError: [Errno 13] Permission denied` when executed as service user `minime`. Furthermore, when the unhandled runner exception occurred, the coordinator stopped the `Run` into `RUNNING_CHECKS` / `NEEDS_HUMAN` (`is_active=false`), but left the associated `Job` trapped in `CHECKS_RUNNING` without a terminal status or error message, preventing legitimate subsequent re-entry under `RecoveryConvergenceService` without unsafe workarounds or model invocation.

This change delivers a robust, fail-closed runtime isolation for deterministic checks cache compatible with Ubuntu service users and Bubblewrap confinement, alongside transactional claim-fenced terminal state transition and authorized re-entry for interrupted checks recovery.

## What Changes

- **UID-Private/Workspace-Isolated Checks Cache**: Configure `ChecksRunner` to isolate bytecode compilation in a private, dedicated cache path owned strictly by the executing process/runtime (or ephemeral isolated location) without relying on shared, unversioned `/tmp/minime_pycache` parent directories. Prohibit recursive `chown` or `chmod 1777` on shared system directories.
- **Bubblewrap Read-Write Bind Compatibility**: Ensure the private checks cache path is properly mounted read-write into the Bubblewrap container confinement profile without polluting host-wide shared paths or colliding with other user namespaces.
- **Claim-Fenced Terminal Job Error Transition on Runner Exception**: When an unexpected pipeline exception occurs while executing `run_checks_only`, ensure the `Job` is transactionally transitioned to `CHECKS_FAILED` with the sanitized error details and claim fencing before or atomically with the `Run` stopping in `NEEDS_HUMAN`.
- **Governed Recovery Re-Entry from Interrupted Checks State**: Allow `RecoveryConvergenceService._validate_checks_only_eligibility` and `recover_checks_only` to authoritatively admit a preserved candidate from the observed interrupted state (`RUNNING_CHECKS` / `NEEDS_HUMAN` Run + `CHECKS_FAILED` or `CHECKS_RUNNING` with proven environmental fault) when authorized by human operator, verifying unchanged candidate SHA, worktree cleanliness, valid durable repository binding, and absence of code-level faults, strictly without re-running OpenSpec APPLY or dispatching AI models.
- **Zero Ingestion / Zero Model Invocation Guarantee**: Enforce that recovery from this state never dispatches implementer LLM calls, preserves candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced` intact, and records durable audit evidence.

## Capabilities

### Modified Capabilities
- `deterministic-checks-runner`: Define process-private / runtime-isolated bytecode cache requirements and Bubblewrap sandbox bind mount guarantees for checks execution.
- `scheduler-and-recovery-convergence`: Define atomic claim-fenced terminal state transitions on checks pipeline errors and governed re-entry validation for runs interrupted during checks recovery.

## Impact

- `src/minime/services/checks_runner.py`: Update bytecode cache directory generation to use private user/job runtime path and ensure sandbox directory mounts.
- `src/minime/services/agent_confinement.py`: Ensure private checks cache directory is bound read-write into the sandbox when confinement is active.
- `src/minime/services/execution_pipeline.py`: In `run_checks_only`, wrap execution in proper error handling to transition `Job` to `CHECKS_FAILED` with claim validation on unhandled exceptions.
- `src/minime/services/orchestration_service.py`: Ensure coordinator failure handling transitions `Job` coherently before/alongside `_stop_coordinator_run`.
- `src/minime/services/recovery_convergence_service.py`: Update checks-only eligibility and recovery handler to admit runs in `RUNNING_CHECKS` / `NEEDS_HUMAN` with environmental fault evidence.
- `tests/test_pilot_checks_recovery_postgres.py` / `tests/test_checks_runner_isolation.py`: Adversarial tests validating cache permissions under distinct UIDs, Bubblewrap confinement, and claim fencing.
