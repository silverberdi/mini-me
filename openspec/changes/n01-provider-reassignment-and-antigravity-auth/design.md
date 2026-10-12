# Design

## Durable human reassignment

The completed, idempotent `OperatorActionRecord` for REASSIGN is the durable source of the explicit executor choice. REASSIGN acquires the existing `run:<run_id>` recovery claim, verifies the linked Job and target provider, applies `Job.current_executor` and the reassignment counter through the claim-fenced repository update, and commits that state together with the action record. It does not call continuation or a provider. Existing JobHandoff rows remain historical evidence.

When resolving executor choice, the newest successful REASSIGN action wins only when it is newer than the pending automatic handoff. Otherwise the existing handoff behavior remains unchanged. Recovery convergence must not apply an older pending handoff over that operator intent. The separate CONTINUE action continues through the existing claim/fencing and execution path. Existing provider health, capacity, provider selection, same-SHA suppression, and reassignment ceilings remain authoritative; counters and attempt history are not reset.

## Credential projection

Extend the existing `AgentRuntimeState`/`AgentProcessConfinement.runtime_session` credential projection to accept a narrowly named Antigravity auth source. Copy one regular, non-symlink file into the attempt-private home under the exact relative path required by the CLI. Validate owner/group/mode and source identity before and after copying, restrict destination permissions, collect sensitive string values for output redaction, compare the private copy digest after execution, and fail closed if it changed. Do not project `.gemini` directories, host HOME, or unrelated files. Reuse the same runner/confinement implementation for implementer and reviewer.

Bubblewrap continues to bind only the assigned worktree writable and the private attempt state writable; runtime remains read-only, `/run` remains private, and all current network isolation options are preserved.

## Verification boundary

Unit tests can verify path allowlisting, permissions, redaction, rotation handling, and mount arguments. Provider authentication proof requires Linux Bubblewrap and the real Antigravity CLI `agy models` command (catalog/auth only, no inference). If either is unavailable, the result is explicitly unverified and cannot be reported as a pass.
