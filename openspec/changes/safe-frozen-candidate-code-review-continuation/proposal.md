## Why

N01 already has a frozen candidate and a passing current check batch, but its exceptional review gate has no safe path to complete the independent CODE_REVIEW without risking re-entry into implementation or checks. This Change makes that preserved checkpoint reviewable through the existing Control Plane while keeping the ordinary autonomous delivery loop unchanged.

## What Changes

- Add a fenced, review-only continuation for an exact frozen candidate, using the existing Run/Job, claim, recovery, DeepSeek Direct reviewer, budget, and durable evidence authorities.
- Require the latest complete configured check batch for the exact candidate SHA and generation; retain historical failures without treating them as current or deleting them.
- Bind one-shot exceptional review authorization, reservation, dispatch checkpoint, and durable review evidence to the same candidate and action, with fail-closed behavior for uncertain dispatch.
- Prevent generic continuation from changing a review-authorization hold back to implementation or rerunning checks.
- Reconcile the stale OpenSpec/provider guidance needed to express the already-canonical DeepSeek Direct reviewer role; do not change provider policy.
- Preserve ordinary autonomous review continuation, candidate history, and human-only merge authority.

## Capabilities

### New Capabilities

- `frozen-candidate-code-review-continuation`: Safely complete an independent, read-only CODE_REVIEW for an exact frozen candidate from an exceptional review gate, while preserving fencing, accounting, lifecycle, and ordinary-flow guarantees.

### Modified Capabilities

None. The behavior is scoped as a new review-only continuation mode; existing ordinary-flow requirements remain unchanged.

## Impact

- Likely integration surfaces: `ControlPlaneService`, `RecoveryConvergenceService`, `OrchestrationService`, `DeepSeekCodeReviewService`, the existing safe review-finalization collaborators, durable action/reservation/review repositories, and current API/CLI/status projections.
- Tests: PostgreSQL + Git recovery/review tests, Control Plane authorization/idempotency tests, review-service tests, and ordinary autonomous-flow regression tests.
- Documentation: minimal reconciliation of `openspec/config.yaml` and `docs/CHANGE_DELIVERY_CONTRACT.md` where their historical fallback language conflicts with the higher-precedence canonical DeepSeek Direct reviewer policy.
- No new provider, scheduler, general budget architecture, or database migration unless implementation evidence proves existing durable records cannot express the required linkage. No production action, N01 execution, provider call, merge, or deployment is authorized by this proposal.
