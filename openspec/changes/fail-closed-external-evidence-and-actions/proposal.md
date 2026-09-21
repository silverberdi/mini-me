# Proposal: Fail-Closed External Evidence and Actions

## Why

Currently in mini me, several external adapters (e.g. `GitHubAdapter`, Git execution wrappers, OpenSpec filesystem handlers, provider execution services, and deployment update scripts) return implicit `bool` values, `None`, or fallback to fabricated success defaults (such as returning `issue #1`, `PVTI_mock_*`, or returning `True` when an exception or 404 is caught).

This creates a systemic failure class where external side effects or state queries cannot be distinguished between true success, true failure, network timeouts, unobservable states, missing authorizations, or ambiguous execution outcomes. When an external operation times out or returns an unobservable response, downstream callers (such as `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and `ContainerPreviewService`) may proceed as if the operation succeeded or may blindly re-execute non-idempotent side effects.

Under the Canonical Lifecycle Correction Program (Stage B), no external operation MAY be treated as successful without positive, verifiable evidence of postconditions (`UNKNOWN != SUCCESS`, `FAILURE != SUCCESS`, `AMBIGUOUS != SUCCESS`). Synthetic IDs, fake URLs, title-only issue deduplication, unconditional 404-success, and `return True` defaults must be completely eliminated from production code.

Furthermore, retry safety must fail closed (`RetrySafety.UNKNOWN` by default; unproven retries are strictly `UNSAFE`), operation identity must be tied to deterministic operation keys (`operation_key`), and historical action execution evidence must never substitute for current-state remote observation when a caller requires current truth.

## What Changes

- Introduce a canonical, strongly typed external outcome contract (`ExternalActionResult[T]`) with explicit outcome states (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`) and explicit fail-closed retry safety enums (`RetrySafety.SAFE`, `UNSAFE`, `UNKNOWN`).
- Eliminate all default success parameters (`source_adapter` and `reason_code` must be explicitly specified; default `reason_code = "ok"` and default `source_adapter = "github"` are removed).
- Define deterministic outcome classification rules:
  - `SUCCESS`: Postcondition authoritatively observed.
  - `FAILURE`: Confirmed rejection or non-achievement with authoritative evidence.
  - `UNKNOWN`: Query/observation truth unobservable, but no uncertain mutating side effect was sent or accepted.
  - `AMBIGUOUS`: Mutating request sent/accepted whose remote effect cannot currently be established.
- Require stable operation keys (`operation_key` bound to project, action type, target item, and generation/correlation identity) with embedded markers/bindings for issue, PR, and branch operations, eliminating title-only deduplication.
- Require observe-before-repeat idempotency logic after `AMBIGUOUS` or `UNKNOWN` outcomes:
  1. Authoritatively observe remote state.
  2. If postcondition observed -> `COMPLETED`.
  3. If absence proven AND `RetrySafety.SAFE` -> retry authorized.
  4. If observation is `UNKNOWN`/`AMBIGUOUS` or absence inconclusive -> DO NOT repeat automatically.
- Differentiate historical action execution evidence (`OrchestrationExternalAction` in `COMPLETED`) from current external state observation. Stored completion evidence prevents duplicate side effects but does NOT substitute for current-state observation when callers require current remote truth.
- Require fail-closed branch deletion: 404 alone does NOT mean success unless repository/ref identity is authoritatively established and ref absence is confirmed (`ALREADY_ABSENT`).
- Require provider execution services to distinguish process exit code 0 from output artifact sufficiency (`EVIDENCE_INSUFFICIENT` -> `NEEDS_HUMAN` rather than false success).
- Require deployment operations to separate deployment action success (`DEPLOY_ACTION_SUCCESS`) from production reachability/health verification truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).
- Refactor callers (including `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and API endpoints) to consume typed outcomes and fail closed on `FAILURE`, `UNKNOWN`, or `AMBIGUOUS`.

## Capabilities

### New Capability: Fail-Closed External Evidence and Actions
Provides a unified, strongly typed outcome model and fail-closed postcondition verification for all external side effects and observations across GitHub, Git, OpenSpec, execution providers, and deployment services, guaranteeing that unobserved or ambiguous outcomes never advance execution state.
