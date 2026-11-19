## Why

The first autonomous N01 execution reached the real Codex CLI but failed before inference because Bubblewrap exposed no writable private state location. That local confinement failure was recorded as a provider failure, and the existing Run/Job now need a safe canonical continuation after the workspace is reconstructed.

## What Changes

- Give each confined implementer/reviewer process a private, per-attempt writable state and temporary area while keeping the assigned worktree as the only writable code tree.
- Project the already-authorized Codex credentials into that private area without exposing the persistent credential directory; detect credential rotation and fail explicitly unless it can be preserved safely.
- Normalize proven local confinement/runtime initialization errors as `ENVIRONMENT_UNAVAILABLE` without penalizing provider health or consuming corrective retry/reassignment budgets.
- Preserve canonical `CONTINUE` semantics for the existing Run/Job and require WorktreeManager to reconstruct a deleted workspace only from durable identity, branch, base and published-artifact evidence.

## Capabilities

### New Capabilities
- `agent-runtime-confinement`: isolated writable runtime state and secret-safe Codex CLI execution under OS confinement.
- `durable-run-continuation`: safe continuation of an existing Run/Job when its durably owned worktree is absent.

### Modified Capabilities
- None.

## Impact

Affected areas include `AgentProcessConfinement`, CLI implementer/reviewer runners, execution outcome parsing/governance and health reporting, WorktreeManager/ControlPlane continuation, and their focused Linux/PostgreSQL tests. No production state, provider policy, scheduler admission policy, or N01 implementation is changed. This is not a UI change. It uses existing host credentials and durable repository/worktree authorities; it introduces no new credentials, database, or authentication system.
