# Proposal: Local Worker Capability Routing Policy

## Why
Empirical server A/B benchmarking on the mini-me Ubuntu host (`silverman@192.168.0.194`) established two critical operational facts:
1. **Model Capacity & Hardware Boundary:** Qwen 14B (`qwen2.5-coder:14b-instruct-q4_K_M`) is non-viable on current server hardware (GTX 1050 2GB VRAM + 87% CPU offload), timing out twice at 180-second HTTP adapter deadlines. Qwen 14B MUST NOT be introduced into local worker routing.
2. **Task Class Insufficiency & Diagnosis Deficit:** For Qwen 7B (`qwen2.5-coder:7b-instruct-q4_K_M`), Attempt 1 timed out at 180s; Attempt 2 returned `NO_CHANGE_JUSTIFIED` in ~26s ("The test already matches the current discovery/readiness contract"), but the deterministic validator failed (`assert 0 == 1`). This proves Qwen 7B is hardware-executable for small warm turns, but a task class label alone (`TEST_AUTHORING`, `SMALL_CODE_FIX`) is insufficient evidence of local model suitability when unknown diagnosis or discovery is required.

Local worker execution MUST be governed by a deterministic, pre-inference **Capability Routing Policy**. This policy evaluates structural complexity, risk profiles, task surfaces, file allowlist boundaries, and typed mechanical explicitness evidence BEFORE invoking Ollama or model inference.

## What Changes
- **Deterministic Capability Router (`LocalWorkerCapabilityRouter`):** Introduce a pre-inference routing decision engine that evaluates whether a work unit is eligible for local Qwen 7B execution (`LOCAL_ELIGIBLE`) or must emit an escalation signal to `EXISTING_PROVIDER_POLICY` (`ESCALATE_PROVIDER_POLICY`).
- **Reuse Task Complexity & Risk Classification:** Consume the existing provider-agnostic `TaskClassificationSnapshot` produced by `TaskComplexityRiskClassifier`. For `PRE_EXECUTION` stage, require `complexity == TaskComplexity.LOW` and `completeness == ClassificationCompleteness.PARTIAL` with an empty `missing_signals` list (as canonical `classify_pre_execution` initializes completeness to `PARTIAL` and never produces `COMPLETE`). Snapshots with `MINIMAL` completeness or non-empty `missing_signals` MUST escalate.
- **Typed Explicitness Evidence Model (`LocalRoutingEvidence`):** Introduce a structured, typed evidence model passed by upstream callers containing mechanical operation type (`LocalMechanicalOperation`), mutation mode (`LocalMutationMode`), single target file boundary, context-supplied authoritative changes, and deterministic acceptance flags. Routing decisions MUST NOT parse natural-language instructions or rely on prompt heuristics.
- **Zero-Tolerance Sensitive Risk Gate:** Require `NONE` for all sensitive risk dimensions (`architectural_impact`, `persistence_impact`, `security_auth_impact`, `production_runtime`, `provider_orchestration`, `destructive_operations`, `deployment_config`). Only `code_change_breadth` may be `NONE` or `LOW`. Any non-`NONE` value in sensitive dimensions escalates.
- **Pre-Inference Gate Integration:** Integrate capability routing inside `LocalWorkerService.run()` prior to Ollama preflight, context packaging, or model dispatch. Refused tasks return `PreflightStatus.NOT_QUALIFIED` and emit `EscalationTarget.EXISTING_PROVIDER_POLICY` with zero Ollama API calls and zero inference tokens.
- **Mutating vs Read-Only Differentiation:** Mutating tasks (`SMALL_CODE_FIX`, `TEST_AUTHORING`, etc.) require strict single-file allowed boundaries and context-supplied authoritative changes. Non-mutating tasks (`LOG_ANALYSIS`) cannot mutate Git and are evaluated under read-only rules while failing closed on secrets/security paths.
- **Canonical Model Identity:** Canonical local routing target remains exclusively `qwen2.5-coder:7b-instruct-q4_K_M`. Qwen 14B is strictly excluded.
- **Fail-Closed Governance:** Any missing snapshot, incomplete classification (`MINIMAL` or non-empty `missing_signals`), non-LOW complexity (`MEDIUM`, `HIGH`, `UNKNOWN`), multi-file scope, missing/untrusted `LocalRoutingEvidence`, or policy uncertainty fails closed to `ESCALATE_PROVIDER_POLICY`.

## Non-Goals
- Modifying canonical Qwen 7B model identity or introducing Qwen 14B.
- Modifying `TaskComplexityRiskClassifier` or embedding provider/routing logic inside it.
- Modifying existing primary provider policies (Codex / Antigravity), OpenRouter drain policy, or reviewer independence rules.
- Implementing automatic cloud provider dispatch within this change (provider selection remains OUT OF SCOPE; caller consumes escalation signal).
- Implementing adaptive or learned routing.
- LLM self-classification of eligibility.
