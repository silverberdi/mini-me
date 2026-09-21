# Proposal: Fail-Closed External Evidence and Actions

## Why

Currently in mini me, several external adapters (e.g. `GitHubAdapter`, Git execution wrappers, OpenSpec filesystem handlers, provider execution services, and deployment update scripts) return implicit `bool` values, `None`, or fallback to fabricated success defaults (such as returning `issue #1`, `PVTI_mock_2`, or returning `True` when an exception or 404 is caught).

This creates a systemic failure class where external side effects or state queries cannot be distinguished between true success, true failure, network timeouts, unobservable states, missing authorizations, or ambiguous execution outcomes. When an external operation times out or returns an unobservable response, downstream callers (such as `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and `ContainerPreviewService`) may proceed as if the operation succeeded or may blindly re-execute non-idempotent side effects.

Under the Canonical Lifecycle Correction Program (Stage B), no external operation MAY be treated as successful without positive, verifiable evidence of postconditions (`UNKNOWN != SUCCESS`, `FAILURE != SUCCESS`, `AMBIGUOUS != SUCCESS`). Synthetic IDs, fake URLs, and `return True` defaults must be completely eliminated from production code.

## What Changes

- Introduce a canonical, strongly typed external outcome contract (`ExternalActionResult[T]`) with explicit outcome states: `SUCCESS`, `FAILURE`, `UNKNOWN`, and `AMBIGUOUS`.
- Eliminate all fabricated default success paths (`return True` on exception, mock IDs like `PVTI_mock_*`, dummy issue `#1`, synthetic URLs) across production adapters (`GitHubAdapter`, `ReadinessGitHubStub`, etc.).
- Require observe-before-act or observe-postcondition verification for GitHub REST/CLI operations (issue creation, issue closure, project item addition/editing, pull request lookup, remote branch deletion).
- Require explicit return code, stderr/stdout, and SHA verification for Git operations (ancestry, branch push, ls-remote, worktree deletion, checkout).
- Require verifiable filesystem postcondition confirmation for OpenSpec sync, archive, and validation operations.
- Require provider execution services to distinguish process exit code 0 from output evidence sufficiency (`EVIDENCE_INSUFFICIENT` -> `NEEDS_HUMAN` rather than false success).
- Require deployment operations to separate deployment action success (`DEPLOY_ACTION_SUCCESS`) from production reachability/health verification truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).
- Extend `OrchestrationExternalAction` and `ExternalActionStatus` to serve as a generic observe-before-repeat idempotency primitive across Git, GitHub, OpenSpec, and service side effects.
- Refactor callers (including `PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`, and API endpoints) to consume typed outcomes and fail closed on `FAILURE`, `UNKNOWN`, or `AMBIGUOUS`.

## Capabilities

### New Capability: Fail-Closed External Evidence and Actions
Provides a unified, strongly typed outcome model and fail-closed postcondition verification for all external side effects and observations across GitHub, Git, OpenSpec, execution providers, and deployment services, guaranteeing that unobserved or ambiguous outcomes never advance execution state.
