## 1. Governed authorization path

- [x] 1.1 Add conditional Control Plane discovery and validation for explicit reauthentication CONTINUE without generic force. Evidence: `tests/test_n01_auth_recovery_convergence.py` action discovery, timestamp/ack rejection, and no-health-promotion cases.
- [x] 1.2 Carry and validate the one-shot authorization under RecoveryConvergenceService claim/fence and OrchestrationService resume. Evidence: fenced active-WAITING_CAPACITY recovery decision test; identity, health timestamp, action type, explicit acknowledgment, and duplicate action-ID rejection.
- [x] 1.3 Permit exactly one matching implementer attempt in ExecutionPipeline while preserving AUTH_REQUIRED until normalized remote outcome; record authorization evidence durably. Evidence: pipeline dispatch validation and durable attempt-marker tests; successful mock remote outcome recovers Codex health, while existing auth/quota outcome suites retain AUTH_REQUIRED/quota mapping.

## 2. Regression coverage

- [x] 2.1 Test local reauthentication acknowledgment without local/remote health promotion, and rejection of absent/stale/mismatched authorization.
- [x] 2.2 Test actual normalized SUCCESS, AUTH_ERROR, and QUOTA_LIMIT outcome mappings without real provider inference. Evidence: `test_execution_pipeline.py` auth-recovery runner path plus existing `test_provider_health.py` and `test_provider_auth_readiness_and_recovery.py` mappings.
- [x] 2.3 Test active WAITING_CAPACITY Run recovery, consumed authorization replay prevention, and independent reviewer capacity preservation. Evidence: fenced recovery unit test, replay rejection, and candidate-preservation test with unavailable Antigravity.

## 3. Validation and handoff

- [x] 3.1 Run focused provider-health, Control Plane, recovery, and execution pipeline tests; run Ruff and strict OpenSpec validation. Evidence: 100 focused tests PASS; Ruff check PASS; changed production modules/new test Ruff format check PASS; OpenSpec change strict PASS; `git diff --check` PASS. The full existing execution-pipeline module has Linux-confinement-dependent failures on this macOS host (exit 126), separately confirmed as `AgentProcessConfinement` unavailable; the targeted integration test passes.
- [ ] 3.2 Verify no schema/production/provider side effects, update task evidence, and prepare a Draft PR. Pending branch push and Draft PR creation.
