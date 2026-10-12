## Context

See `proposal.md` for incident motivation. The existing recovery validator already proves ownership, canonical path and binding, Run/Job identity, original base B, remote ancestry, recovery branch/snapshot, unique snapshot event, and (for `CREATED`) physical Git worktree registration, ownership marker, exact branch/HEAD, and only unstaged modifications below the authorized OpenSpec change path. The normal execution pipeline enters this path under canonical Run continuation authority.

## Goals / Non-Goals

**Goals:** narrowly authorize a crash-interrupted in-flight attempt without weakening the shared recovery validator or rewriting durable attempt counters/history.

**Non-Goals:** changing `PREMATURE_STOP` normalization globally, changing recovery lifecycle, allowing this exception for absent/`DELETED` worktrees, repairing arbitrary Git state, or creating another Run/Job.

## Decisions

- Keep the existing `_verify_deleted_worktree_recreation()` path as the sole recovery gate. Add a separate predicate for the exceptional attempt state, callable only when ownership is `CREATED`; retain the existing `ENVIRONMENT_UNAVAILABLE` and `PROVIDER_FAILURE` cases as before.
- Accept `PREMATURE_STOP` only when the latest durable attempt has no completion timestamp or duration and its attempt number is exactly one greater than the persisted finalized `Job.attempt_count`. This preserves, rather than normalizes, the observed in-flight-attempt/counter difference.
- Require post-attempt durable recovery evidence bound through the authoritative Job/Run relationship: a matching `JOB_INTERRUPTED` for the implementer with no candidate and the original base; a later matching `JOB_RECOVERED`; and a later `ORCHESTRATION_RECOVERED` for the same Run at IMPLEMENTING. Events must match project/change/operation identities and have ordered timestamps after the attempt start. Missing or contradictory evidence fails closed.
- Rely on canonical Control Plane CONTINUE and the existing Run claim/fencing validation for concurrency authority; do not acquire hidden claims inside WorktreeManager. Keep the existing Git status, snapshot, remote publication, ancestry, and byte-level artifact verification in force.
- Do not mutate attempt rows or `Job.attempt_count` as part of recognition. The continuation pipeline remains responsible for its ordinary attempt semantics.

## Risks / Trade-offs

- [Recovery events may be unavailable or incomplete] → deny continuation; the operator can inspect durable evidence rather than bypassing the gate.
- [Duplicate or out-of-order recovery events could be ambiguous] → require exact identities and event ordering; reject contradictory matching evidence.
- [Job attempt count differs from the active attempt number] → accept only the precise one-in-flight-attempt relation and preserve both persisted values.

## Migration Plan

No database migration is needed. Deploy through the normal reviewed application release. Rollback removes only the additional recognition path; no persisted state is rewritten by this change.
