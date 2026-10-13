# Design: AUTH_REQUIRED recovery for an existing CREATED worktree

## Decision

Extend the existing worktree recovery verifier rather than adding a parallel continuation path. The exception applies only when durable ownership is CREATED and the original physical worktree is still present. The existing DELETED path and its accepted outcomes remain unchanged.

## Authorization evidence

The new CREATED-only predicate requires all attempts to be uniquely numbered and contiguous through `job.attempt_count`; the unique latest attempt must be AUTH_REQUIRED and completed. Every attempt must have a provider-failure classification (or the single narrowly qualified terminal same-SHA classification below), no progress classification beyond NO_PROGRESS, and stable start/end SHA when both are recorded. Job and Run candidates remain absent and their project, change, generation-stage, and original base lineage must match.

The anti-loop policy remains authoritative for automatic execution: a same-SHA duplicate is not retried automatically. A later human-authorized continuation may reuse an intact CREATED workspace only when exactly one suppression exists and it is the latest attempt: AUTH_REQUIRED, SAME_SHA_NO_PROGRESS, NO_PROGRESS, NEEDS_HUMAN, same SHA as the immediately preceding AUTH_REQUIRED / PROVIDER_PREFLIGHT_FAILURE / NO_PROGRESS attempt, and corroborated by the unique durable SAME_SHA_RETRY_SUPPRESSED event for that Job/attempt/SHA. Repeated duplicates, a different outcome, progress, missing or contradictory event evidence, and all other duplicate placements fail closed. The normal current CONTROL_PLANE DRIVE_CONTINUATION claim/fence and all worktree integrity checks remain mandatory.

The caller must be inside a current canonical Control Plane continuation: the newest run claim decision must bind the exact Run/project/change, use CONTROL_PLANE and DRIVE_CONTINUATION, remain EXECUTING during worktree validation, be newer than the failed attempt, and carry the live matching fence token. This is corroboration for the current continuation, not authority to mutate another workspace.

All existing checks still run afterward: validated managed binding and repository identity; authoritative remote base observation and ancestry; canonical path, Git worktree registration, ownership marker, original branch and single artifact-only snapshot; no candidate; no pending/unknown/ambiguous external action; allowed worktree status; and exact published OpenSpec artifact materialization.

## Fail-closed behavior

Missing or inconsistent attempt evidence, an expired/mismatched claim, non-CONTROL_PLANE decision, non-CREATED ownership, absent directory, candidate/progress evidence, any unauthorized Git path/status, or publication mismatch is rejected. Error wording distinguishes validation of an existing CREATED worktree from recreation of a DELETED worktree.

No attempt, Job, Run, ownership, snapshot, counter, or recovery event is rewritten by this change.

## Validation

Use focused unit tests and an isolated PostgreSQL plus local Git remote/worktree integration. The integration uses a diagnostic runner only; it must preserve the same Run/Job and stop before any provider inference.
