# Proposal: Fail-Closed External Evidence and Actions

## Why

Currently in mini me, several external adapters (e.g. `GitHubAdapter`, Git execution wrappers, OpenSpec filesystem handlers, provider execution services, and deployment update scripts) return implicit `bool` values, `None`, or fallback to fabricated success defaults (such as returning `issue #1`, `PVTI_mock_*`, or returning `True` when an exception or 404 is caught).

This creates a systemic failure class where external side effects or state queries cannot be distinguished between true success, true failure, network timeouts, unobservable states, missing authorizations, or ambiguous execution outcomes. When an external operation times out or returns an unobservable response, downstream callers (such as `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and `ContainerPreviewService`) may proceed as if the operation succeeded or may blindly re-execute non-idempotent side effects.

Under the Canonical Lifecycle Correction Program (Stage B), no external operation MAY be treated as successful without positive, verifiable evidence of postconditions (`UNKNOWN != SUCCESS`, `FAILURE != SUCCESS`, `AMBIGUOUS != SUCCESS`). Synthetic IDs, fake URLs, title-only issue deduplication, unconditional 404-success, and `return True` defaults must be completely eliminated from production code.

Furthermore, retry safety MUST fail closed (`RetrySafety.UNKNOWN` by default; mutating actions are strictly `RetrySafety.UNSAFE` to prevent duplicate re-transmission), machine-readable `reason_code` MUST be strictly typed (`ExternalReasonCode`), operation identity MUST be tied to deterministic operation keys (`operation_key`), and historical action execution evidence MUST NOT substitute for current-state remote observation when a caller requires current truth.

## What Changes

- Introduce a canonical, strongly typed external outcome contract (`ExternalActionResult[T]`) with explicit outcome states (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`), strictly typed reason codes (`reason_code: ExternalReasonCode`), optional `provider_detail: str | None`, and explicit fail-closed retry safety enums (`RetrySafety.SAFE`, `UNSAFE`, `UNKNOWN`).
- Define exact `RetrySafety` semantics: `RetrySafety` indicates whether retransmitting/re-executing the operation is safe. Read-only queries MAY be `SAFE`; mutating actions (even on `SUCCESS`) are strictly `UNSAFE` to prevent duplicate side effects. Duplicate execution prevention for mutating actions relies on `operation_key` + historical `COMPLETED` action records + observe-before-repeat protocol.
- Define strict, deterministic outcome classification rules:
  - `SUCCESS`: Postcondition authoritatively observed.
  - `FAILURE`: Confirmed rejection or non-achievement with authoritative evidence (e.g. 401/403 auth rejection, 404 Not Found on read/query, validation failure).
  - `UNKNOWN`: Read-only observation/query truth unobservable when NO uncertain mutating side effect was sent or accepted.
  - `AMBIGUOUS`: Mutating request sent/accepted whose remote effect cannot currently be established (e.g. POST/PATCH/DELETE timeout, loss of connection after send, CLI abnormal exit after mutating command sent).
- Require stable operation keys (`operation_key` bound to project, action type, target item, and generation/correlation identity) with embedded markers/bindings for issue, PR, and branch operations, eliminating title-only deduplication.
- Require observe-before-repeat protocol after `AMBIGUOUS` or `UNKNOWN` outcomes:
  1. Authoritatively observe remote state.
  2. If postcondition observed -> `COMPLETED`.
  3. If absence proven AND `RetrySafety.SAFE` -> retry MAY be authorized.
  4. If observation is `UNKNOWN`/`AMBIGUOUS` or absence inconclusive -> DO NOT repeat automatically.
- Require explicit fail-closed GitHub Project item lookup and binding: confirmed 404 absence or 401/403 auth rejection yields `FAILURE` (`NOT_FOUND` / `AUTH_REQUIRED`), unobservable queries yield `UNKNOWN` (`UNOBSERVABLE`/`TIMEOUT`/`RATE_LIMITED`), and synthetic IDs (`PVTI_mock_*`) are strictly forbidden.
- Differentiate historical action execution evidence (`OrchestrationExternalAction` in `COMPLETED`) from current external state observation. Stored completion evidence prevents duplicate side effects but does NOT substitute for current-state observation when callers require current remote truth.
- Require fail-closed branch deletion: 404 alone does NOT mean success unless repository/ref identity is authoritatively established and ref absence is confirmed (`ALREADY_ABSENT`).
- Require provider execution services to distinguish process exit code 0 from output artifact sufficiency (`EVIDENCE_INSUFFICIENT` -> `NEEDS_HUMAN` rather than false success).
- Require deployment operations to separate deployment action success (`DEPLOY_ACTION_SUCCESS`) from production reachability/health verification truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).
- Refactor callers (including `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and API endpoints) to consume typed outcomes and fail closed on `FAILURE`, `UNKNOWN`, or `AMBIGUOUS`.

## Capabilities

### New Capability: Fail-Closed External Evidence and Actions
Provides a unified, strongly typed outcome model and fail-closed postcondition verification for all external side effects and observations across GitHub, Git, OpenSpec, execution providers, and deployment services, guaranteeing that unobserved or ambiguous outcomes never advance execution state.
