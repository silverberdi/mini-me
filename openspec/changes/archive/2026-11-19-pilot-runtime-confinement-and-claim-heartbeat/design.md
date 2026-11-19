## Context

See `proposal.md` for background and problem statement from the first autonomous Ubuntu pilot execution (Issue #157, Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`).

The system currently enforces:
- OS-level write confinement via Bubblewrap on Linux (`AgentProcessConfinement.wrap_command()`).
- Fenced compare-and-swap (CAS) transitions backed by PostgreSQL `recovery_claims` table with monotonic `fence_token` and `lease_expires_at`.
- Isolated claim heartbeat renewal via `PostgresPersistenceUnitOfWork.renew_claim_heartbeat_isolated()`.

However, the direct coordinator drive path (`OrchestrationService.drive_coordinator()`) admitted work without establishing an active `OperationalHeartbeat`, allowing the 60-second lease to lapse during a 10-minute inference pass. Furthermore, Bubblewrap omitted `--dev /dev`, causing `ChecksRunner` to fail when `pytest` opened `os.devnull`.

## Goals / Non-Goals

**Goals:**
- Provide standard unprivileged virtual devices (`/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/pts`) inside the Bubblewrap sandbox using `--dev /dev` without exposing host devices.
- Define an explicit, contract-backed ownership model for `OperationalHeartbeat` lifecycle across direct admission and recovery continuation paths.
- Enforce strict fencing fail-closed behavior: a worker that loses its claim MUST NOT perform any database writes (no `_stop_run()`, no `NEEDS_HUMAN`, no commit), raising `StaleClaimError` and rolling back.
- Ensure idempotent cleanup and claim release in `finally` blocks without thread leaks.
- Establish real Linux integration test gates for Bubblewrap device access, negative write confinement, and PostgreSQL fenced concurrency.
- Provide a clean continuation plan for Ubuntu pilot Run (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) and candidate (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`) without re-running agent authoring.

**Non-Goals:**
- Modifying PostgreSQL database schema (existing `recovery_claims` table and Alembic migrations remain unchanged).
- Modifying candidate code in `mini-me-fixture` (`sanitize-filename-token` implementation and tests are already complete and valid).
- Weakening process confinement, removing write protection outside worktree, or altering Darwin sandbox behavior.
- Altering the 60-second default lease duration or 15-second heartbeat interval constants.

## Decisions

### Decision 1: Mount unprivileged virtual devices in Bubblewrap using `--dev /dev`
- **Approach**: In `AgentProcessConfinement.wrap_command()`, append `["--dev", "/dev"]` immediately following `["--ro-bind", "/", "/"]` on Linux.
- **Rationale**: Bubblewrap's `--dev /dev` constructs an unprivileged virtual `/dev` mount inside the container. It instantiates virtual character devices (`null`, `zero`, `full`, `random`, `urandom`, `tty`, `pts`, `shm`) with valid permissions in unprivileged user namespaces (`CLONE_NEWUSER`), bypassing the kernel's `nodev` restriction on ordinary root bind-mounts. It does not bind arbitrary host devices or expose host block devices.
- **Alternatives Considered**:
  - *Individual bind-mount of `/dev/null`*: Fails because unprivileged user namespaces enforce `MS_NODEV` on bind mounts from the host root, producing `EACCES` on `open()`.
  - *Executing checks unconfined*: Rejected as a critical violation of engineering discipline and workspace isolation.

### Decision 2: Explicit Heartbeat Ownership Contract by Trajectory
- **Rejection of Informal Sentinels**: Rather than attaching improvised mutable attributes to Pydantic `RecoveryClaimContext`, the system defines explicit ownership of `OperationalHeartbeat` lifecycle by entry trajectory:
  1. **Direct Admission Trajectory (`orchestrate start` / `SchedulerService.admit_work_item(drive_admitted=True)`)**:
     - The admission authority acquires the claim (`claim_key="run:<run_id>"`).
     - `drive_coordinator()` receives `manage_heartbeat=True` (default).
     - `drive_coordinator()` instantiates `OperationalHeartbeat(claim_context=claim_context, interval_seconds=15, lease_seconds=60, renew_claim=uow.renew_claim_heartbeat_isolated)`.
     - In a `finally` block, `drive_coordinator()` stops the heartbeat thread and idempotently releases the claim.
  2. **Recovery Continuation Trajectory (`orchestrate resume` / `RecoveryConvergenceService`)**:
     - `RecoveryConvergenceService` acquires the claim and manages its own outer `OperationalHeartbeat`.
     - When invoking `drive_coordinator()`, it explicitly passes `manage_heartbeat=False`.
     - `drive_coordinator()` does NOT instantiate an inner heartbeat thread and does NOT release the claim on exit.
     - The outer recovery context stops the heartbeat and releases the claim in its own `finally` block.
- **Idempotent Claim Release**:
  - `PostgresRecoveryClaimRepository.release_claim()` is strictly idempotent. Releasing an already released, expired, or superseded claim is a safe no-op returning `False`.
  - Stopping `OperationalHeartbeat` sets the stop event and joins the background thread with timeout, guaranteeing no leaked threads on normal completion or error exit.

### Decision 3: Fencing Fail-Closed without Post-Loss Database Mutations
- **Authority Loss Invariant**: If a worker's heartbeat fails or its fence token is superseded by another node:
  - The stale worker has LOST mutation authority.
  - The stale worker MUST NOT invoke `_stop_run()`, MUST NOT write `NEEDS_HUMAN` to PostgreSQL, and MUST NOT commit the session.
  - The stale worker MUST NOT attempt to release the claim, as it now belongs to a successor owner.
- **Implementation Mechanism**:
  - On each cycle of `drive_coordinator()` and immediately before any stage transition or database write, the worker validates:
    ```python
    if heartbeat is not None and heartbeat.heartbeat_failed:
        raise StaleClaimError("Heartbeat renewal failed; aborting without database mutation.")
    validate_claim_context_authoritative(self.uow, claim_context)
    ```
  - When a long-running external subprocess (e.g. LLM inference) completes, the worker checks claim validity before recording results or freezing candidates.
  - If invalid, `StaleClaimError` is raised, the database session is rolled back, and the process exits. The valid claim holder or background reconciler is the sole authority that decides and commits durable updates.

### Decision 4: Ubuntu Fixture Pilot Continuation Plan
- **State Preservation**:
  - Run ID: `8e7ebec8-9eff-478b-bae3-cf686ea91be2`
  - Candidate SHA: `2fcad0ef73eb4766ca1bb6249a081cb4070ecced` (already committed in worktree `.minime/worktrees/b917a9f0-0354-4805-863f-7ab4e7ada559`)
  - Backlog item & change: `sanitize-filename-token`
- **Continuation Sequence (post-merge & deployment only)**:
  1. PR #158 is merged into `main` and deployed to `/opt/minime/app`.
  2. The operator explicitly authorizes continuation:  
     `minime orchestrate resume 8e7ebec8-9eff-478b-bae3-cf686ea91be2 --path /opt/minime/repos/mini-me-r01-e2e-20261014`
  3. The resume workflow acquires a fresh recovery claim and drives the coordinator.
  4. The coordinator skips re-implementing `sanitize-filename-token` because the candidate is already committed, executing `ChecksRunner` under the fixed Bubblewrap sandbox.
  5. All 16 unit tests pass, candidate integrity is verified, DeepSeek Direct code review executes, and the GitHub Draft PR is produced.

## Risks / Trade-offs

- **[Risk] Long blocking subprocess cannot be instantly preempted**: If a claim expires while an LLM inference call is blocked in HTTP, the thread cannot be forcibly aborted.  
  $\rightarrow$ **Mitigation**: The worker strictly checks claim authority immediately upon subprocess return. If the fence was lost during the call, all external results are discarded without committing to PostgreSQL.
- **[Risk] Database connection drop during heartbeat**:  
  $\rightarrow$ **Mitigation**: `OperationalHeartbeat` flags `heartbeat_failed = True`. The coordinator detects this on the next iteration and halts fail-closed without mutating subsequent stages.
- **[Risk] Bubblewrap unavailable on non-Linux platforms**:  
  $\rightarrow$ **Mitigation**: The code branches on `confinement_mechanism == "bubblewrap"`. Darwin uses `sandbox-exec` and platforms without Bubblewrap fail closed per existing policy.
