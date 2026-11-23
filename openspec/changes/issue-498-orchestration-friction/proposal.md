## Why

Issue #498 groups several observed orchestration dead ends: agent output formatting can turn a completed native workflow into a pause without an actionable gate, authorized corrections can fail to re-enter Apply, oversized review context can prevent useful review, and a merge response can be treated as a permanent failure before GitHub's mergeability state is known. These paths make valid work difficult to resume and obscure the actual blocker.

## What Changes

- Base Explore and workflow completion decisions on observable native OpenSpec results and resulting artifacts, not brittle prose sentinels or a required agent-authored completion token; retain genuine human questions and fail-closed behavior for missing or invalid artifacts.
- Ensure a blocked stage caused by missing recovery authorization exposes the current reason and an actionable, authorized recovery path through the existing gate/API flow.
- Allow Apply to re-enter on the same candidate when verified review corrections authorize remediation, while retaining stage-invocation, candidate-identity, retry, and regression safeguards.
- Make reviewer input bounded and useful for large diffs: exclude irrelevant generated/static output where safely identifiable, preserve review-relevant source changes, and respect the configured prompt transport. Verify the actual failure mode instead of assuming every oversized prompt is an OS `ARG_MAX` failure.
- Treat GitHub merge HTTP 405 as retryable only when a read-back shows mergeability is still unknown/transient; use bounded retry and preserve immediate fail-closed handling for branch protection, conflicts, or other permanent rejection.
- Keep the existing autonomy/time metrics work in Issue #489 out of this Change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-propose`: Native Explore/workflow evidence must not depend on brittle output markers when native results and artifacts provide the evidence; genuine questions and real failures remain actionable.
- `run-autorecovery-and-autonomous-continuation`: A recovery hold must expose its reason and an available authorized operator action instead of becoming an opaque pause.
- `openspec-native-apply-and-verify`: Verified review corrections must permit guarded Apply re-entry on the same candidate.
- `reviewer-execution-contract`: Large review inputs must be bounded without discarding relevant source evidence or relying on an unverified process-size assumption.
- `two-phase-pr-and-closure`: Merge retries must distinguish transient unknown mergeability from permanent GitHub policy/conflict rejection.

## Impact

Likely touchpoints are Explore/workflow result handling and stage transitions in `orchestration_coordinator.py` and `agent_runner.py`, recovery gate construction in the existing API/UI path, review diff/prompt preparation, and GitHub merge handling in the existing adapter/coordinator. No new provider, workflow engine, durable queue, metric, database entity, deployment path, or OpenSpec substitute is proposed. Existing OpenSpec workflows, candidate identity, human authorization, branch protections, and fail-closed security boundaries remain authoritative.

## Validation sequence

Pre-merge Verify covers automated checks against the committed candidate SHA and must report skipped or unavailable integration evidence explicitly. A real Mini Me Run can be observed only after the merged release is deployed, so that observation is a post-deployment acceptance follow-up: it must remain marked pending until its Run and stage evidence are observed, and it must not be reported as pre-merge E2E evidence. Keep Issue #498 open through that observation and resolve any failure before documentary closure.
