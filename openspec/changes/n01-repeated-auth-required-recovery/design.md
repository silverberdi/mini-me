## Context

The previous recovery exception tied authorization to one duplicate attempt and one suppression event. Durable JobAttempt and Event records already contain per-attempt identity, outcome, productivity, SHA, timestamps, and suppression evidence.

## Goals / Non-Goals

**Goals:**
- Validate every attempt and suppression independently, without a fixed maximum chain length.
- Require a current canonical CONTROL_PLANE / DRIVE_CONTINUATION decision and active matching fenced claim newer than the last attempt.
- Reuse the existing CREATED-only verifier and preserve its downstream repository, ownership, snapshot, publication, candidate, and external-action checks.

**Non-Goals:**
- Changing anti-loop decisions or automatic retries.
- Allowing recovery for DELETED or physically absent worktrees.
- Rewriting attempt history, counters, events, claims, or snapshots.
- Renewing credentials or executing inference.

## Decisions

1. Treat a contiguous attempt history as an evidence chain, not as a retry count. The first attempt must be a genuine provider or preflight failure with its matching productivity classification. Every attempt must be completed, have NO_PROGRESS, and have identical non-empty start/end SHA. A duplicate must be AUTH_REQUIRED / SAME_SHA_NO_PROGRESS / NEEDS_HUMAN and match the immediately preceding AUTH_REQUIRED attempt's SHA.
2. Require exactly one SAME_SHA_RETRY_SUPPRESSED event for each duplicate attempt and no other suppression events in the scoped project/change history. Each event must bind the same Job, attempt number, candidate SHA, canonical reason prefix, and occur after that attempt completed but before the next attempt started. A saturated event read fails closed.
3. Keep the current fenced Control Plane DRIVE_CONTINUATION decision as the human continuation authority. It must match the Run/project/change, remain EXECUTING under the active CAS-valid claim, and be newer than the latest attempt. Automatic retry remains governed by existing policy.
4. Do not alter any DELETED recovery logic; this exception remains reachable only for CREATED ownership with the physical worktree present and still subject to all existing verifier checks.

Alternatives rejected: allowing arbitrary SAME_SHA_NO_PROGRESS, accepting any count based on latest-event presence, or imposing a hard-coded maximum attempt count. These either weaken anti-loop protection or fail to model evidence per attempt.

## Risks / Trade-offs

- [Incomplete event reads could hide extra suppression evidence] → reject a saturated repository read rather than infer completeness.
- [A valid long-running history increases validation work] → process the finite durable attempt chain linearly; no arbitrary attempt limit is imposed.
- [AUTH_REQUIRED may coexist with real code changes] → require per-attempt no-progress SHA equality plus unchanged downstream Git cleanliness and candidate checks.

## Migration Plan

No schema migration. Deploy through normal review/merge. Rollback is code-only; durable history remains untouched.
