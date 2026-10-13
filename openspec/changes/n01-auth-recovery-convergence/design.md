## Context

Provider health is durable. `AUTH_REQUIRED` intentionally blocks automatic probes, while execution admission requires an available primary. A local CLI login is not evidence that the remote API accepts credentials. See the proposal and delta specs for the externally observable contract.

## Goals / Non-Goals

**Goals:** Let an operator authorize one governed implementation attempt after reauthentication, without promoting provider health before a real normalized result.

**Non-Goals:** Reset provider health from local login state, bypass scheduler/fallback policy generally, or change review independence/capacity rules.

## Decisions

- Keep provider health `AUTH_REQUIRED` until the existing runner returns a normalized remote outcome. Reuse `ProviderHealthService.record_outcome()` for SUCCESS, AUTH_ERROR, and quota/rate-limit mappings.
- Represent authorization as a typed, action-scoped permit bound to provider, project, run, job, generation, expected health observation timestamp, and action request identity. Persist it in the existing fenced recovery decision/attempt evidence; do not add schema.
- Require explicit operator confirmation and exact current health timestamp. The permit can bypass only the primary-AVAILABLE precheck for one implementer dispatch; it cannot enable OpenRouter, alter retry limits, or bypass claims/fencing.
- Consume authorization before dispatch and reject reuse. A failed or interrupted attempt requires a new operator action; this prevents implicit retry loops.
- Permit the currently active WAITING_CAPACITY run only when the linked job and all identities match and no candidate exists. Preserve the normal CONTINUE contract for other states.
- Keep the existing WAITING_CAPACITY Run/Job checkpoint durable until the fenced orchestration resume has accepted the auth-recovery decision. If resume fails before the authorization is attached to a durable JobAttempt, restore/retain the same active WAITING_CAPACITY checkpoint, persist a BLOCKED recovery decision and stop event, and require a fresh operator CONTINUE request. Do not count the permit as consumed or claim a dispatch occurred.
- A successful resume consumes the authorization only when a JobAttempt contains its exact action request ID. If resume returns without that durable marker, treat it as a pre-dispatch failure and preserve the existing worktree and attempt history.
- Continue through the existing execution pipeline and normal outcome normalization. Independent review remains required; unavailable Antigravity leaves a valid candidate waiting for review.

## Risks / Trade-offs

- [A remote request may fail before a normalized response] → Keep health unchanged unless a trustworthy normalized result exists; retain the attempt and require fresh operator authorization.
- [Provider state changes after the operator observes it] → Compare the exact persisted `updated_at` at action acceptance and again under the active claim immediately before dispatch.
- [Retry could be repeated] → Bind the permit to a unique action request ID and reject any already-consumed permit; no generic force flag participates.

## Migration Plan

No schema migration. Deploy through the normal human-approved release path. Rollback is code-only; already recorded attempts, actions, health observations, and candidates remain durable and are not rewritten.

## Open Questions

None.
