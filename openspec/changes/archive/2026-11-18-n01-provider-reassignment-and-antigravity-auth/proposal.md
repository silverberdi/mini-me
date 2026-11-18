# N01 provider reassignment and confined Antigravity authentication

## Why

The existing N01 Run can be stopped for human attention after Antigravity reaches the same-SHA retry guard. A human REASSIGN request is currently recorded only on the domain Run object and may be overwritten by an older pending JobHandoff during recovery or pipeline executor selection. Separately, the confined Antigravity CLI does not receive its narrowly scoped authentication state.

## What changes

- Persist explicit operator reassignment as an idempotent Control Plane action and apply the selected executor through the existing recovery-claim-fenced Job repository authority.
- Make RecoveryConvergenceService and ExecutionPipeline honor the latest successful human reassignment over an older automatic handoff, without resetting attempts or bypassing provider health, capacity, or reassignment ceilings.
- Project only the authorized Antigravity CLI credential file into a private per-process runtime, redact its values, detect unpersisted rotation, and always destroy the projection.
- Keep the existing worktree, Bubblewrap filesystem, process, and network boundaries.

## Scope

This change addresses the durable continuation path for the existing N01 Run/Job only. It does not create execution records, invoke a provider during REASSIGN, or change admission, provider policy, retry, or anti-loop rules.

## Out of scope

- Production data or execution.
- N02–N05.
- Provider architecture, scheduler/admission policy, or sandbox redesign.
- Automatic persistence of refreshed credentials.

## Acceptance

An isolated integration test demonstrates human REASSIGN to Codex followed by a separate authorized CONTINUE reaches the Codex runner for the same Run/Job while preserving three historical attempts and SAME_SHA_RETRY_SUPPRESSED evidence. Negative tests prove exhausted/unavailable providers and the reassignment ceiling remain enforced. Confined runtime tests prove only the Antigravity auth file is copied and that rotation is not persisted. A real Bubblewrap `agy models` check is required before claiming provider-authentication proof; it must not invoke inference.
