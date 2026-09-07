# Proposal: Minimal Local Worker Bootstrap

## Problem Statement
mini me currently routes all substantive implementation to remote CLI/HTTP providers
(Codex / Antigravity / OpenRouter drain / DeepSeek audit). Routine, bounded, LOW-risk
mechanical coding work (small code fixes, test authoring, log analysis, small refactors,
small API changes, small UI polish) otherwise consumes scarce frontier quota and network
dependencies even though a local model would be sufficient to produce the work.

mini me already treats Qwen as advisory only. There is no canonical, deterministic,
bounded path for a local worker to execute a constrained LOW-risk coding task through
local Ollama and feed that work into the existing deterministic validation + escalation
seams. Building that path opportunistically (full scheduler/provider-policy redesign,
capability registries, telemetry, routing, benchmarking) is explicitly out of scope and
belongs to the future Adaptive AI Execution backlog program.

## Proposed Change
Introduce the **smallest canonical capability** required to execute bounded LOW-risk work
through local Ollama using exactly the model `qwen2.5-coder:7b-instruct-q4_K_M`:

1. A minimal generic local/Ollama provider adapter.
2. Exact model identity persisted/represented: `qwen2.5-coder:7b-instruct-q4_K_M`.
3. Deterministic preflight: Ollama reachable, required model present, execution readiness.
4. Bounded timeout / cancellation / process cleanup.
5. A constrained execution harness with explicitly scoped task envelopes.
6. LOW-risk task eligibility with a canonical allowlist of task classes:
   `SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`, `SMALL_REFACTOR`,
   `API_SMALL_CHANGE`, `UI_SMALL_POLISH`.
7. Explicit forbidden/high-risk task classes and forbidden surfaces.
8. At most one local corrective attempt (no unbounded retry loop).
9. Deterministic validation remains authoritative: the local model never decides that its
   own work is successful.
10. Clean escalation to the existing provider policy when the local worker is not
    admissible/authoritative.
11. Minimal, structured execution evidence:
    provider, model, task class, attempt, result, validation result, escalation.
12. Local Qwen carries no merge/review/audit authority.

## Acceptance Criteria
1. Canonical model identity is stored exactly as `qwen2.5-coder:7b-instruct-q4_K_M`.
2. Deterministic tests prove the tests release does not require a live Ollama.
3. Unavailable Ollama fails preflight with a deterministic reason.
4. Missing required model fails preflight with a deterministic reason.
5. Allowed LOW-risk task class (e.g. `SMALL_CODE_FIX`) is admitted by the eligibility gate.
6. Any forbidden/high-risk class/surface is deterministically refused/escalated.
7. Structured output validation is enforced; `NO_CHANGE_JUSTIFIED` is a valid, accepted result.
8. Execution is bounded by a timeout; cancellation cleans up underlying work when present.
9. The corrective loop is capped at exactly one local corrective attempt.
10. Escalation to existing provider policy is clean and recorded in evidence.
11. Local Qwen has no reviewer/auditor/merge/approve authority anywhere.

## Non-Goals (future Adaptive AI Execution backlog program)
These are explicitly NOT implemented here and must not be built opportunistically:
- `ai-provider-model-capability-registry`
- `execution-attempt-effectiveness-telemetry`
- `task-complexity-risk-classification`
- `shared-skill-execution-harness-framework`
- `ollama-qwen-local-worker-integration`
- `adaptive-provider-model-routing`
- AI Operations dashboard, benchmarking/calibration, Cursor integration,
  OpenRouter policy redesign.

No scheduler wiring, no orchestration core changes, no database schema/migration changes are
introduced by this bootstrap. Scheduler restart is not required.
