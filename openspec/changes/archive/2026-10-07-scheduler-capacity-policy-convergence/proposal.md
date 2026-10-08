## Why

The scheduler is responsible for answering the core question: *"Given the current backlog/job and current provider/reviewer capacity truth, may mini me safely admit and execute work now?"*

Prior iterations and historical drafts (notably `provider-capacity-drain-policy`, which is hereby **SUPERSEDED / DO_NOT_IMPLEMENT**) suffered from several critical policy gaps and divergence:
1. **Configured vs Runtime Truth**: Admission decisions were evaluated against static or configured provider defaults rather than authoritative runtime provider health, quota cooldown, and capacity lifecycle state.
2. **Missing Reviewer Pair Evaluation**: The scheduler admitted work if an implementer appeared available, without verifying that a safe executable pair exists (`SAFE_EXECUTABLE_PAIR_EXISTS` — at least one eligible implementer and at least one compatible, independent reviewer available under `ModelIndependencePolicy`).
3. **Drain Fallback Conflation**: OpenRouter drain fallback was conflated with new admission capacity, violating the canonical rule that paid drain fallback may only complete eligible in-flight work and must never start new READY work.
4. **Failure Cause Conflation & Unproductive Retries**: Post-execution outcomes and local lifecycle defects (such as missing credentials, invalid configuration, missing tool harnesses, or text-only provider execution without verifiable repository-editing evidence) were misdiagnosed as temporary capacity exhaustion, placing jobs into inappropriate cooldown or infinite paid retry loops.
5. **Decision Conflation**: Downstream execution/outcome states and lifecycle blocks were conflated into an ad-hoc fifth scheduler capacity decision (`REFUSED`), rather than mapping cleanly to the four canonical operational decisions: `RUN`, `DRAIN`, `WAIT`, and `NEEDS_HUMAN`.
6. **Epistemic Dishonesty**: Arbitrary recovery timers and fabricated ETAs were generated even when provider reset times were unmeasured or unknown.
7. **Entry-Point Divergence**: CLI commands, REST API endpoints (`/api/v1/scheduler/tick`), TUI actions, and the daemon background loop had slightly divergent admission checks or bypass paths.

This change establishes a single, authoritative, converged scheduler admission and capacity policy that resolves these defects deterministically.

## What Changes

- **Unified Four-Decision Operational Taxonomy**: Standardize scheduler decisions across all evaluation paths strictly to `RUN`, `DRAIN`, `WAIT`, and `NEEDS_HUMAN`. Remove `REFUSED` as a standalone capacity decision, maintaining a strict distinction between scheduler admission decisions and downstream execution/outcome classifications.
- **Mandatory Safe Executable Pair Check (`SAFE_EXECUTABLE_PAIR_EXISTS`)**: Require that admission verify the simultaneous availability and independence of both an eligible implementer and an independent reviewer before issuing `RUN`. Answers executability without ranking, provider scoring, capability selection, or capacity reservation.
- **Strict Drain Fallback Confinement**: Strictly enforce that `DRAIN` policy allows continuation of active, in-flight work items already in progress under exhausted primaries via canonical OpenRouter drain fallback (`src/minime/services/openrouter_eligibility.py`), but unconditionally refuses admission of new work items.
- **Pre-Admission vs Post-Execution Separation**: Distinguish pre-admission observable conditions (e.g. provider cooldowns, auth presence, config validity) from post-execution attempt outcomes (e.g. `EVIDENCE_INSUFFICIENT`, `HARNESS_UNAVAILABLE`).
- **No Unproductive Retries for `EVIDENCE_INSUFFICIENT`**: Enforce that textual provider success without verifiable repository-editing evidence produces `EVIDENCE_INSUFFICIENT` -> `NEEDS_HUMAN`, with zero automatic corrective retries, zero capacity cooldown, and zero repeated paid incapable invocations.
- **Strict Human Gate vs Predecessor Wait Separation**: Explicit human approval/merge gates map strictly to `NEEDS_HUMAN`, while automated predecessor/dependency progression maps to `WAIT`.
- **Single Authoritative Admission Engine**: Route all tick and admission requests (CLI, REST API, TUI, daemon) through the converged `SchedulerService.evaluate_admission` engine in `src/minime/services/scheduler_service.py`.
- **Epistemic Honesty**: Reject fabricated ETAs or speculative recovery times when provider quota reset intervals are unknown; reflect truthful `UNKNOWN` status (`has_deterministic_eta=False`).

## Capabilities

### Modified Capabilities
- `autonomous-queue-work-selection`: Updated to require paired implementer-reviewer capacity validation (`SAFE_EXECUTABLE_PAIR_EXISTS`), unified 4-decision taxonomy, strict drain isolation, and strict `EVIDENCE_INSUFFICIENT` / human gate mapping before admitting work items.
- `provider-resilience-and-exhaustion`: Reconciled so scheduler capacity evaluation queries authoritative runtime health from `ProviderHealthService` without bypassing cooldown or probe locks.

### Superseded Artifacts
- `provider-capacity-drain-policy`: Marked **SUPERSEDED / DO_NOT_IMPLEMENT**; all overlapping scheduler capacity and admission semantics are formally replaced by this change.

## Non-Goals

- Do NOT implement AI model/provider dynamic routing or capability selection.
- Do NOT implement benchmark calibration or weighted complexity scoring.
- Do NOT rank providers, select the "best" pair, or reserve future provider capacity.
- Do NOT alter provider selection algorithms or add speculative provider switching.
- Do NOT implement automated merge or bypass human merge gates.
- Do NOT add new database storage engines or bypass PostgreSQL/Alembic migration lifecycle.

## Impact

- Domain models: Enforce standard 4-decision operational enum (`RUN`, `DRAIN`, `WAIT`, `NEEDS_HUMAN`) and structured evaluation rationale models.
- Core services: Update `SchedulerService.evaluate_admission` to verify `SAFE_EXECUTABLE_PAIR_EXISTS`, respect drain limits, fail closed on `EVIDENCE_INSUFFICIENT` with `NEEDS_HUMAN`, and classify human gates accurately.
- API and CLI: Align `/api/v1/scheduler/tick` and `minime scheduler tick` to invoke the exact same unified admission pipeline.
- Tests: Add comprehensive test scenarios covering all normative failure scenarios and parity across all entry points.
