## Context

See `proposal.md` for background and problem statement from the first autonomous Ubuntu pilot execution (Issue #157).

The system currently enforces:
- OS-level write confinement via Bubblewrap on Linux (`AgentProcessConfinement.wrap_command()`).
- Fenced compare-and-swap (CAS) transitions backed by PostgreSQL `recovery_claims` table with monotonic `fence_token` and `lease_expires_at`.
- Isolated claim heartbeat renewal via `PostgresPersistenceUnitOfWork.renew_claim_heartbeat_isolated()`.

However, the direct coordinator drive path (`OrchestrationService.drive_coordinator()`) was admitted directly without binding an active `OperationalHeartbeat`, allowing the 60-second lease to lapse during a 10-minute inference pass. Simultaneously, Bubblewrap omitted `--dev /dev`, causing `ChecksRunner` to fail when `pytest` opened `os.devnull`.

## Goals / Non-Goals

**Goals:**
- Provide standard unprivileged virtual devices (`/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/pts`) inside the Bubblewrap sandbox without exposing arbitrary host device nodes.
- Maintain active background heartbeat renewal throughout `drive_coordinator()` execution when a `claim_context` is present.
- Avoid duplicate heartbeat loops when `drive_coordinator()` is invoked under an existing outer recovery heartbeat.
- Ensure fail-closed termination with durable evidence preservation if heartbeat renewal fails or claim fence is superseded.
- Preserve existing Ubuntu pilot Run (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) and candidate (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`) for clean resumption.

**Non-Goals:**
- Modifying PostgreSQL database schema (existing `recovery_claims` table and Alembic migrations remain unchanged).
- Modifying candidate code in `mini-me-fixture` (`sanitize-filename-token` implementation and tests are already complete and valid).
- Weakening process confinement, removing write protection outside worktree, or altering Darwin sandbox behavior.
- Altering the 60-second default lease duration or 15-second heartbeat interval constants.

## Decisions

### Decision 1: Mount standard devtmpfs in Bubblewrap using `--dev /dev`
- **Approach**: In `AgentProcessConfinement.wrap_command()`, append `["--dev", "/dev"]` immediately following `["--ro-bind", "/", "/"]`.
- **Rationale**: Bubblewrap's `--dev` flag constructs an unprivileged, kernel-managed `devtmpfs` inside the container. It instantiates virtual character devices (`null`, `zero`, `full`, `random`, `urandom`, `tty`, `pts`, `shm`) with valid permissions in unprivileged user namespaces (`CLONE_NEWUSER`), bypassing the kernel's `nodev` restriction on ordinary root bind-mounts.
- **Alternatives Considered**:
  - *Individual bind-mount of `/dev/null`*: Fails because unprivileged user namespaces enforce `MS_NODEV` on bind mounts from the host root, producing `EACCES` on `open()`.
  - *Executing checks unconfined*: Rejected as a critical violation of engineering discipline and workspace isolation.

### Decision 2: OperationalHeartbeat integration in `drive_coordinator`
- **Approach**: In `OrchestrationService.drive_coordinator()`, wrap the stage execution loop in an `OperationalHeartbeat` context manager when `claim_context` is provided:
  - Check whether `claim_context` is already managed by an existing running heartbeat thread (e.g. via an internal sentinel or tracking attribute) to prevent nested duplicate threads.
  - If unmanaged, launch `OperationalHeartbeat` with `interval_seconds=15`, `lease_seconds=60`, and `renew_claim=uow.renew_claim_heartbeat_isolated`.
  - On each cycle of `drive_coordinator()`, check `heartbeat.heartbeat_failed`. If failed (e.g. lease lost or fence superseded), immediately abort stage transitions and exit safely with `NEEDS_HUMAN` stop outcome, preserving durable state.
- **Rationale**: `renew_claim_heartbeat_isolated` creates a dedicated, short-lived SQLAlchemy session to update `heartbeat_at` and `lease_expires_at` in PostgreSQL and commits immediately. This keeps the claim fresh across multi-minute inference and check operations without holding locks or polluting the worker's session.
- **Alternatives Considered**:
  - *Increasing claim lease to 1 hour*: Rejected because an abandoned or crashed worker would block recovery for an hour, defeating the purpose of fenced leases.
  - *Heartbeat inside `execute_queued_job` only*: Rejected because other stages (e.g. checks execution, multi-attempt evaluation, PR preparation) can also take substantial time; managing the heartbeat at the coordinator level covers all stages uniformly.

### Decision 3: Removal Ledger & Compatibility
- **Replaced logic**: Direct unheartbeated drive in `drive_coordinator` and deviceless Bubblewrap mount in `wrap_command`.
- **Callers affected**:
  - `OrchestrationService.drive_coordinator`: Enhanced with heartbeat context manager; signature remains backward-compatible.
  - `AgentProcessConfinement.wrap_command`: Enhanced with `--dev /dev`; arguments and return type remain unchanged.
  - All existing consumers and tests continue to work without modification.

## Risks / Trade-offs

- **[Risk] Multiple heartbeats on the same claim**: If recovery convergence launches a heartbeat and `drive_coordinator` launches another, database contention or double-renewal could occur.  
  $\rightarrow$ **Mitigation**: Detect active heartbeat on `claim_context` before spawning; reuse the existing heartbeat when already present.
- **[Risk] Subprocess attempts device access beyond virtual standard devices**: Could a malicious script manipulate other devices?  
  $\rightarrow$ **Mitigation**: Bubblewrap `--dev` only creates standard unprivileged pseudo-devices (`null`, `zero`, `random`, `urandom`, `pts`). No host block devices or raw disk controllers are exposed.
- **[Risk] Bubblewrap unavailable on non-Linux platforms**:  
  $\rightarrow$ **Mitigation**: The code branches on `confinement_mechanism == "bubblewrap"`. Darwin uses `sandbox-exec` and platforms without Bubblewrap fail closed per existing policy.
