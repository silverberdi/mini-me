# Proposal: Local Worker Capability Routing Policy

## Why
Empirical server A/B benchmarking on the mini-me Ubuntu host (`silverman@192.168.0.194`) established two critical operational facts:
1. **Model Capacity & Hardware Boundary:** Qwen 14B (`qwen2.5-coder:14b-instruct-q4_K_M`) is non-viable on current server hardware (GTX 1050 2GB VRAM + 87% CPU offload), timing out twice at 180-second HTTP adapter deadlines. Qwen 14B MUST NOT be introduced into local worker routing.
2. **Task Class Insufficiency:** Qwen 7B (`qwen2.5-coder:7b-instruct-q4_K_M`) completed warm execution in ~26s, but returned `NO_CHANGE_JUSTIFIED` for a failing test fixture, proving that a task class label alone (`TEST_AUTHORING`, `SMALL_CODE_FIX`) is insufficient evidence of local model suitability.

Local worker execution MUST be governed by a deterministic, pre-inference **Capability Routing Policy**. This policy evaluates structural complexity, risk profiles, task surfaces, file allowlist boundaries, and mechanical explicitness evidence BEFORE invoking Ollama or model inference.

## What Changes
- **Deterministic Capability Router (`LocalWorkerCapabilityRouter`):** Introduce a pre-inference routing decision engine that evaluates whether a work unit is eligible for local Qwen 7B execution (`LOCAL_ELIGIBLE`) or must be escalated directly to `EXISTING_PROVIDER_POLICY` (`ESCALATE_PROVIDER_POLICY`).
- **Reuse Task Complexity & Risk Classification:** Consume the existing provider-agnostic `TaskClassificationSnapshot` produced by `TaskComplexityRiskClassifier`. Require `complexity == LOW` (from `TaskComplexity`) and `completeness == COMPLETE` (from `ClassificationCompleteness`).
- **Deterministic Explicitness Contract:** Require structured evidence of mechanical explicitness (e.g. single target file boundary, explicit operation type, authoritative desired replacement supplied in context, zero unresolved discovery/debugging flags). Tasks requiring root-cause investigation, multi-module semantic reasoning, architectural inference, or ambiguous discovery MUST escalate to `EXISTING_PROVIDER_POLICY`.
- **Pre-Inference Gate Integration:** Integrate capability routing inside `LocalWorkerService.run()` prior to Ollama preflight, context packaging, or model dispatch. Refused tasks incur zero Ollama API calls and zero inference tokens.
- **Mutating vs Read-Only Differentiation:** Mutating tasks (`SMALL_CODE_FIX`, `TEST_AUTHORING`, etc.) require strict single-file allowed boundaries. Non-mutating tasks (`LOG_ANALYSIS`) cannot mutate Git and are evaluated under read-only rules while failing closed on secrets/security paths.
- **Canonical Model Identity:** Canonical local routing target remains exclusively `qwen2.5-coder:7b-instruct-q4_K_M`. Qwen 14B is strictly excluded.
- **Fail-Closed Governance:** Any missing snapshot, incomplete classification (`PARTIAL`, `MINIMAL`), non-LOW complexity (`MEDIUM`, `HIGH`, `UNKNOWN`), multi-file scope, or policy uncertainty fails closed to `ESCALATE_PROVIDER_POLICY`.

## Non-Goals
- Modifying canonical Qwen 7B model identity or introducing Qwen 14B.
- Modifying `TaskComplexityRiskClassifier` or embedding provider/routing logic inside it.
- Modifying existing primary provider policies (Codex / Antigravity), OpenRouter drain policy, or reviewer independence rules.
- Implementing adaptive or learned routing.
- LLM self-classification of eligibility.
