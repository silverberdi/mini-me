# Implementation Tasks: Local Worker Capability Routing Policy

## Phase 1: Domain Models & Reason Codes
- [ ] 1.1 Define `LocalRoutingVerdict` enum (`LOCAL_ELIGIBLE`, `ESCALATE_PROVIDER_POLICY`, `INSUFFICIENT_EVIDENCE`) in `src/minime/local_worker/models.py`.
- [ ] 1.2 Define `LocalRoutingReasonCode` enum (`LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`, `COMPLEXITY_NOT_LOW`, `CLASSIFICATION_UNKNOWN`, `CLASSIFICATION_INCOMPLETE`, `HIGH_RISK_SURFACE`, `FORBIDDEN_SURFACE`, `SCOPE_TOO_BROAD`, `MULTI_MODULE_SCOPE`, `TASK_NOT_MECHANICALLY_EXPLICIT`, `TASK_CLASS_NOT_LOCAL`, `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK`, `MISSING_ALLOWED_FILE_BOUNDARY`) in `src/minime/local_worker/models.py`.
- [ ] 1.3 Define `LocalRoutingDecision` frozen dataclass/Pydantic model in `src/minime/local_worker/models.py`.

## Phase 2: Capability Router Implementation
- [ ] 2.1 Write unit test suite `tests/test_local_worker_capability_router.py` verifying all 24 spec scenarios prior to production logic implementation.
- [ ] 2.2 Implement `LocalWorkerCapabilityRouter` in `src/minime/local_worker/capability_router.py`.
- [ ] 2.3 Implement snapshot gate (checking pre-execution classification snapshot presence, stage `PRE_EXECUTION`, and completeness `ClassificationCompleteness.COMPLETE`).
- [ ] 2.4 Implement complexity & risk gates (`TaskComplexity.LOW` check, zero HIGH-risk dimension verification).
- [ ] 2.5 Implement surface & task-class gates (checking allowed task classes and forbidden surface families).
- [ ] 2.6 Implement explicit boundary gate (verifying $\le 1$ allowed file boundary for mutating tasks).
- [ ] 2.7 Implement mechanical explicitness evaluation (distinguishing small reasoning burden from small file surface).
- [ ] 2.8 Implement read-only task branch (`LOG_ANALYSIS`).
- [ ] 2.9 Enforce canonical Qwen 7B model binding (`qwen2.5-coder:7b-instruct-q4_K_M`) and fail closed on Qwen 14B or unknown models.

## Phase 3: Service Gate Integration
- [ ] 3.1 Write integration tests in `tests/test_local_worker_routing_integration.py` verifying pre-inference refusal and zero Ollama API call dispatch.
- [ ] 3.2 Update `LocalWorkerService.run()` in `src/minime/local_worker/service.py` to evaluate `LocalWorkerCapabilityRouter` before Ollama preflight, context packaging, or model dispatch.
- [ ] 3.3 Ensure refused local tasks immediately return `ServiceOutcome` with refusal evidence and `EscalationTarget.EXISTING_PROVIDER_POLICY`.

## Phase 4: Verification & Governance Validation
- [ ] 4.1 Run full unit and integration test suite (`pytest tests/test_local_worker_*.py`).
- [ ] 4.2 Run OpenSpec strict validation (`openspec validate local-worker-capability-routing-policy --strict --type change`).
- [ ] 4.3 Ensure zero runtime checkout mutation, zero managed repo mutation, and zero scheduler restart.
