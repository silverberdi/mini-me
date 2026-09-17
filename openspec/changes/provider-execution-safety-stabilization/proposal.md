# Proposal: Provider Execution Safety Stabilization

## Why

Production runtime confirmed three defects in the provider execution layer that can silently waste paid quota and fabricate false progress: (1) an unavailable provider with an unknown reset time is treated as immediately probe-eligible, so the scheduler probes Codex roughly once per tick for hours; (2) the Codex availability probe actually runs `codex exec`, consuming real inference capacity instead of a local readiness/auth check; and (3) OpenRouter implementer fallback creates and commits a placeholder `candidate_impl.py` when no real repository-editing harness exists. These must be stabilized now because they directly violate the provider-cost-safety and candidate-truth-integrity non-negotiables.

## What Changes

- Provider health monitoring stops treating unknown reset timing as immediate probe eligibility; unavailable providers use deterministic, bounded cooldown/backoff recovery.
- Health checks separate local readiness (executable present) and authentication readiness from inference capacity; inference-based probes become exceptional, explicitly classified, rate-limited, and observable.
- The Codex availability probe no longer consumes inference capacity as a frequent heartbeat; readiness uses non-inference local checks where the installed CLI supports them.
- OpenRouter (and any provider without a real repository-editing harness) can no longer fabricate an implementation candidate; it returns a truthful governed outcome with no repository mutation, no candidate commit, and no false progress event.
- Candidate truth invariant: a candidate exists only when real repository files were materially changed, are candidate-bound, verifiable, and reviewable.
- Primary implementer/reviewer CLI harnesses are proven to operate deterministically headless, and unsupported/deprecated CLI flags fail preflight instead of consuming a full attempt.
- Timeout, cancellation, and process-group cleanup remain bounded with no orphan subprocesses.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `provider-capacity-tracking`: tighten "Verified capacity reset probing" with deterministic cooldown/backoff and correct the unknown-reset divergence; add "Non-inference readiness checks and expensive probe governance".
- `openrouter-drain-fallback`: add the "No fabricated implementation candidates" prohibition.
- `agent-execution-outcome-governance`: tighten "Fail-closed completion verification" to reject placeholder-only/fabricated candidates.
- `primary-implementer-execution`: tighten "Primary implementer invocation" and "Execution timeout and process control" for headless/non-interactive proving, preflight flag validation, and cancellation cleanup.
- `reviewer-execution-contract`: tighten "Reviewer process execution with timeout and redaction" for read-only, non-interactive, non-mutating behavior.

## Impact

- Runtime: `src/minime/services/provider_health_service.py`, `src/minime/adapters/provider_adapter.py`, `src/minime/services/execution_pipeline.py`, `src/minime/services/scheduler_service.py` (probe cadence), and `src/minime/config.py` (explicit probe cooldown/backoff defaults).
- Persistence: provider probe-attempt state (last probe time, consecutive probe failures) for cooldown/backoff plus probe-execution events for observability.
- Tests: new deterministic regression tests and CLI-compatibility/proving tests.
- No UI surface is affected; no human validation scenarios are required.
- No new provider/model, no OpenCode, no provider/model selector or capability-registry redesign, no telemetry-based routing, no scheduler restart policy change beyond provider-execution safety.
