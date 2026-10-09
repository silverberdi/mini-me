# Implementation Tasks: Local Worker Capability Routing Policy

## Phase 1: Domain Models & Trusted Evidence Construction Authority
- [ ] 1.1 Define `LocalRoutingVerdict` enum (`LOCAL_ELIGIBLE`, `ESCALATE_PROVIDER_POLICY`, `INSUFFICIENT_EVIDENCE`) in `src/minime/local_worker/models.py`.
- [ ] 1.2 Define `LocalMechanicalOperation` enum (`TEXT_REPLACEMENT`, `LITERAL_UPDATE`, `FIXTURE_UPDATE`, `LOG_DIAGNOSTIC`) in `src/minime/local_worker/models.py`.
- [ ] 1.3 Define `LocalMutationMode` enum (`MUTATING`, `READ_ONLY`) in `src/minime/local_worker/models.py`.
- [ ] 1.4 Define `LocalRoutingEvidenceProvenance` enum (`STRUCTURED_OPENSPEC_TASK_METADATA`, `DETERMINISTIC_INTAKE_METADATA`, `OPERATOR_EXPLICIT_MECHANICAL_COMMAND`, `UNTRUSTED_CALLER_PROSE`) in `src/minime/local_worker/models.py`.
- [ ] 1.5 Define `LocalRoutingEvidence` frozen dataclass/Pydantic model in `src/minime/local_worker/models.py`.
- [ ] 1.6 Implement `LocalRoutingEvidenceAuthority` in `src/minime/local_worker/evidence_authority.py` to construct trusted `LocalRoutingEvidence` ONLY from verified canonical sources.
- [ ] 1.7 Define `LocalRoutingReasonCode` enum (`LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`, `COMPLEXITY_NOT_LOW`, `CLASSIFICATION_UNKNOWN`, `CLASSIFICATION_INCOMPLETE`, `HIGH_RISK_SURFACE`, `FORBIDDEN_SURFACE`, `SCOPE_TOO_BROAD`, `MULTI_MODULE_SCOPE`, `TASK_NOT_MECHANICALLY_EXPLICIT`, `TASK_CLASS_NOT_LOCAL`, `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK`, `MISSING_ALLOWED_FILE_BOUNDARY`) in `src/minime/local_worker/models.py`.
- [ ] 1.8 Define `LocalRoutingDecision` frozen dataclass/Pydantic model in `src/minime/local_worker/models.py`.

## Phase 2: Capability Router Implementation
- [ ] 2.1 Write unit test suite `tests/test_local_worker_capability_router.py` verifying all 24 spec scenarios prior to production logic implementation.
- [ ] 2.2 Implement `LocalWorkerCapabilityRouter` in `src/minime/local_worker/capability_router.py`.
- [ ] 2.3 Implement snapshot gate (checking pre-execution classification snapshot presence, stage `PRE_EXECUTION`, completeness `ClassificationCompleteness.PARTIAL`, and direct field check `snapshot.missing_signals == []`).
- [ ] 2.4 Implement zero-tolerance risk gate (verifying sensitive risk dimension strings equal `"NONE"`).
- [ ] 2.5 Implement surface & task-class gates (checking allowed task classes and forbidden surface families).
- [ ] 2.6 Implement explicit boundary gate (verifying $\le 1$ allowed file boundary for mutating tasks).
- [ ] 2.7 Implement mechanical explicitness gate using trusted `LocalRoutingEvidence` from `LocalRoutingEvidenceAuthority` (zero natural-language parsing).
- [ ] 2.8 Implement read-only task branch (`mutation_mode == READ_ONLY` / `LOG_ANALYSIS`).
- [ ] 2.9 Enforce canonical Qwen 7B model binding (`qwen2.5-coder:7b-instruct-q4_K_M`) and fail closed on Qwen 14B or unknown models.

## Phase 3: Service Gate Integration
- [ ] 3.1 Write integration tests in `tests/test_local_worker_routing_integration.py` verifying pre-inference refusal, canonical `PreflightStatus.NOT_QUALIFIED`, and zero Ollama API call dispatch.
- [ ] 3.2 Update `LocalWorkerService.run()` in `src/minime/local_worker/service.py` to evaluate `LocalWorkerCapabilityRouter` before Ollama preflight, context packaging, or model dispatch.
- [ ] 3.3 Ensure refused local tasks immediately return `ServiceOutcome` with refusal evidence, `PreflightStatus.NOT_QUALIFIED`, and `EscalationTarget.EXISTING_PROVIDER_POLICY`.

## Phase 4: Verification & Governance Validation
- [ ] 4.1 Run full unit and integration test suite (`pytest tests/test_local_worker_*.py`).
- [ ] 4.2 Run OpenSpec strict validation (`openspec validate local-worker-capability-routing-policy --strict --type change`).
- [ ] 4.3 Ensure zero production code changes outside designated scope, zero managed repo mutation, and zero scheduler restart.
