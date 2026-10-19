## Why

During the execution of the first autonomous pilot in Ubuntu (Issue #157, Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`), the implementer completed code generation and candidate authoring (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced` with 16 passing unit tests for `sanitize_filename_token`), but the orchestration pipeline encountered two coupled post-implementation defects:

1. **Bubblewrap `/dev` confinement denial**: `AgentProcessConfinement.wrap_command()` configured Bubblewrap on Linux with `--ro-bind / /` without `--dev /dev`. In Linux unprivileged user namespaces, device nodes on standard bind mounts are mounted with `nodev`, causing `pytest` and standard Python I/O to fail with `PermissionError: [Errno 13] Permission denied: '/dev/null'`.
2. **Recovery claim lease expiration and fencing in long-running stages**: `drive_coordinator()` in `OrchestrationService` operated under a 60-second recovery claim lease without an active `OperationalHeartbeat` during slow external agent inference (~10 minutes). Upon completion, the subsequent fenced compare-and-swap stage transition was rejected with `StaleClaimError: recovery claim fence is stale, expired, or superseded`. Furthermore, the recovery heartbeat lacked an explicit lifecycle and ownership contract between direct admission and recovery continuation paths.

This change resolves both defects to ensure uninterrupted, fenced execution and deterministic check verification under process confinement without weakening sandbox boundaries or database isolation.

## What Changes

- **Bubblewrap Unprivileged Virtual Devices**: Update `AgentProcessConfinement.wrap_command()` on Linux to provide standard unprivileged virtual devices (`--dev /dev`) inside the Bubblewrap sandbox. This mounts an unprivileged virtual `/dev` containing `/dev/null`, `/dev/zero`, `/dev/urandom`, and `/dev/pts` while preserving read-only host mounts and strict write confinement to the assigned worktree.
- **Explicit Heartbeat Ownership Contract**: Establish a strict, explicit ownership contract for `OperationalHeartbeat` across execution trajectories:
  - In direct admission (`SchedulerService.admit_work_item(drive_admitted=True)` and `orchestrate start`), `drive_coordinator()` explicitly manages the heartbeat lifecycle (`manage_heartbeat=True`) and performs idempotent cleanup in `finally`.
  - In recovery continuation (`RecoveryConvergenceService` and `orchestrate resume`), the outer recovery authority manages the heartbeat and signals `manage_heartbeat=False` to `drive_coordinator()`, preventing nested duplicate renewal threads and double-release races.
- **Fencing Fail-Closed Invariant (No Writes Without Claim)**: Enforce that workers losing their claim (due to lease expiration, renewal failure, or fence supersession) MUST NOT write to PostgreSQL, MUST NOT attempt to record `NEEDS_HUMAN` or stage outcomes, and MUST NOT release claims belonging to successor owners. The stale worker halts immediately, raises `StaleClaimError`, rolls back the transaction, and leaves durable state intact for authorized recovery.
- **Real Ubuntu Integration and Confinement Gates**: Require authentic integration tests under real Linux Bubblewrap (running actual `pytest` suites and testing negative write isolation) and real PostgreSQL fenced concurrency (simulating stage durations exceeding the lease and fence supersession).
- **Run and Candidate Preservation**: Preserve the existing Run (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) and authoritatively committed candidate (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`), defining an exact continuation plan that completes post-implementation checks and PR creation without repeating LLM inference or code authoring.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `managed-repository-runtime-isolation`: Require unprivileged sandbox environments under Bubblewrap to provide standard virtual devices (`/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/pts`) required by standard POSIX runtimes without permitting writes outside the worktree.
- `scheduler-and-recovery-convergence`: Require direct orchestration coordinator drive to participate in explicit claim heartbeat ownership throughout long-running stages, avoiding duplicate renewal threads, enforcing idempotent release, and failing closed with zero database writes on claim loss.

## Impact

- **Confinement Service (`src/minime/services/agent_confinement.py`)**: Adds `--dev /dev` to Bubblewrap command construction.
- **Orchestration Service (`src/minime/services/orchestration_service.py`)**: Adds explicit `manage_heartbeat` ownership parameter to `drive_coordinator()`, wraps stage execution in `OperationalHeartbeat` when owned, and guarantees fail-closed termination on claim loss.
- **Recovery Service (`src/minime/services/recovery_convergence_service.py`)**: Coordinates explicit heartbeat ownership when invoking `drive_coordinator()`, preventing duplicate threads.
- **Unit and Integration Tests**: Validates Bubblewrap device node access, checks runner execution under real Linux confinement, and verifies coordinator heartbeat renewal and fence supersession under PostgreSQL.
- **Zero Database Schema Changes**: Leverages existing `recovery_claims` table, `OperationalHeartbeat`, and `renew_claim_heartbeat_isolated()` without migration requirements.
