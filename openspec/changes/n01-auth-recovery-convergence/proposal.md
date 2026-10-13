## Why

Provider health can remain durably `AUTH_REQUIRED` after an operator renews local credentials, while automatic probes intentionally refuse to clear that state and execution refuses to start. This change provides a governed, single implementation continuation that lets an authentic remote result—not local login status—reconcile health.

## What Changes

- Allow an explicitly confirmed Control Plane continuation from an active `WAITING_CAPACITY` run only when its linked implementing Job is waiting on the exact provider still marked `AUTH_REQUIRED`.
- Bind one provider attempt to the action identity, actor, exact prior health timestamp, Run/Job identity, and active recovery claim; record that authorization on the durable recovery decision and attempt.
- Keep provider health `AUTH_REQUIRED` until the actual implementation response classifies remote authentication and capacity. Do not add a health reset, inference probe, generic force bypass, or automatic retry.
- Preserve candidates when an independent reviewer is unavailable; never bypass the complementary review gate.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `provider-capacity-tracking`: explicit reauthentication acknowledgment permits one real implementation call as the remote health observation; only its authentic normalized result changes health.
- `operator-actions-control-plane`: expose a confirmation-bound CONTINUE path for the exact active waiting Run/Job without using generic force.

## Impact

Affected areas are ControlPlaneService, RecoveryConvergenceService, OrchestrationService, ExecutionPipeline, provider-health tracking and focused tests. No schema migration is expected: authorization evidence is recorded in existing recovery-decision and JobAttempt JSON fields. No production state, credentials, provider quota, scheduler state, or worktree is changed while authoring this candidate.
