## Why

During the execution of the first autonomous pilot in Ubuntu (Issue #157, Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`), the implementer completed code generation and candidate authoring (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced` with 16 passing unit tests for `sanitize_filename_token`), but the orchestration pipeline encountered two coupled post-implementation defects:

1. **Bubblewrap `/dev` confinement denial**: `AgentProcessConfinement.wrap_command()` configured Bubblewrap with `--ro-bind / /` without `--dev /dev`. In Linux unprivileged user namespaces, device nodes on standard bind mounts are mounted with `nodev`, causing `pytest` and standard Python I/O to fail with `PermissionError: [Errno 13] Permission denied: '/dev/null'`.
2. **Recovery claim lease expiration during long-running stages**: `drive_coordinator()` in `OrchestrationService` operated under a 60-second recovery claim lease without an active `OperationalHeartbeat` during slow external agent inference (~10 minutes). Upon completion, the subsequent fenced compare-and-swap stage transition was rejected with `StaleClaimError: recovery claim fence is stale, expired, or superseded`.

This change resolves both defects to ensure uninterrupted, fenced execution and deterministic check verification under process confinement without weakening sandbox boundaries or database isolation.

## What Changes

- **Bubblewrap Standard Virtual Devices**: Update `AgentProcessConfinement.wrap_command()` on Linux to provide standard virtual devices (`--dev /dev`) inside the Bubblewrap sandbox. This mounts an unprivileged `devtmpfs` with `/dev/null`, `/dev/zero`, `/dev/urandom`, and `/dev/pts` while preserving read-only host mounts and strict write confinement to the assigned worktree.
- **Orchestration Driver Heartbeat Integration**: Update `OrchestrationService.drive_coordinator()` to maintain an `OperationalHeartbeat` for the active `claim_context` throughout stage progression and slow external execution (agent inference and deterministic checks), utilizing isolated database sessions (`renew_claim_heartbeat_isolated`).
- **Heartbeat Deduplication and Fail-Closed Safety**: Ensure that when a claim is already covered by an active heartbeat (such as in recovery convergence resume workflows), nested redundant heartbeats are prevented. If heartbeat renewal fails or the claim is lost/superseded, the coordinator stops safely without mutating subsequent stages.
- **Run and Candidate Preservation**: Preserve the existing Run (`8e7ebec8-9eff-478b-bae3-cf686ea91be2`) and authoritatively committed candidate (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`), allowing resumption without discarding valid implementation work.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `managed-repository-runtime-isolation`: Require unprivileged sandbox environments under Bubblewrap to provide standard virtual devices (`/dev/null`, `/dev/zero`, `/dev/urandom`) required by standard runtimes without permitting writes outside the worktree.
- `scheduler-and-recovery-convergence`: Require the direct orchestration coordinator drive path to maintain background heartbeat renewal for the active recovery claim throughout long-running stages, avoiding duplicate renewal threads and halting safely on claim loss.

## Impact

- **Confinement Service (`src/minime/services/agent_confinement.py`)**: Adds `--dev /dev` to Bubblewrap command construction.
- **Orchestration Service (`src/minime/services/orchestration_service.py`)**: Wraps coordinator drive loop in `OperationalHeartbeat` when `claim_context` is supplied and no outer heartbeat is active.
- **Unit and Integration Tests**: Validates Bubblewrap device node access, checks runner execution under confinement, and verifies coordinator heartbeat renewal during operations exceeding the base lease time.
- **Zero Database Schema Changes**: Leverages existing `recovery_claims` table, `OperationalHeartbeat`, and `renew_claim_heartbeat_isolated()` without migration requirements.
