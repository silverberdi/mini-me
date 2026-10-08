# Tasks: Minimal Local Worker Bootstrap

Instructions: treat `specs/minimal-local-worker-bootstrap/spec.md` as behavioral authority.
Every task must have a completion signal; keep scope to the active change only.

## Task 1 — Canonical model identity and constants
- Add `minime/local_worker/model_identity.py` with:
  - `OLLAMA_PROVIDER = "ollama"`
  - `LOCAL_WORKER_ROLE = "local_worker"` (implement-oriented, never reviewer/auditor)
  - `QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M = "qwen2.5-coder:7b-instruct-q4_K_M"`
  - exact-equality helper.
- Completion: unit test asserting the exact canonical string and exact-equality behavior. ✅

## Task 2 — Local worker task classes and forbidden surfaces
- Add `minime/local_worker/task_classes.py` declaring the allowlist
  (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`, `SMALL_REFACTOR`,
  `API_SMALL_CHANGE`, `UI_SMALL_POLISH`) and forbidden-surface matchers for
  lifecycle/state-machine, provider-policy, security, migrations/db-schema, architecture,
  deployment/runtime-infrastructure, destructive, uncertain-classification.
- Completion: ruff-clean module plus unit tests asserting allowlist membership and that each
  forbidden surface is matched.

## Task 3 — Local worker domain models (structured, deterministic)
- Add `minime/local_worker/models.py` defining Pydantic v2:
  - `LocalTaskEnvelope` (role, task_class, allowed_* , forbidden_* , smallest-patch
    instruction, bounded context, no-architecture, no-unrelated-dependencies)
  - `LocalWorkerResult` structured outputs with confidence, escalation_required,
    escalation_reason and a valid `NO_CHANGE_JUSTIFIED` representation
  - `PreflightResult`, `EligibilityDecision`, `ValidationResult`, `EscalationDecision`
  - `LocalExecutionEvidence` (provider, model, task_class, attempt, result, validation,
    escalation)
- Completion: models import cleanly and serialize with ruff passing. ✅

## Task 4 — Minimal Ollama adapter (offline-testable)
- Add `minime/local_worker/ollama_adapter.py`:
  - preflight reachability (`/api/tags`) and model existence (`/api/show`/tags equality)
  - bounded generate that maps outcomes onto `minime.domain.enums.ProviderResultClass`
  - injected `httpx.AsyncClient`/transport for offline tests
  - timeout/cancellation and cleanup on deadline
- Completion: unit tests (MockTransport) for reachability, model-present, model-missing,
  generate success/failure and no-live-Ollama requirement all pass.

## Task 5 — Eligibility and authority policy
- Add `minime/local_worker/policy.py`:
  - `evaluate_eligibility(task)` LOW-risk admission gate (allowlist + forbidden surfaces +
    files)
  - `local_worker_authorities()` prove no review/audit/merge/approve authority
  - escalation decision to existing provider policy
- Completion: unit tests for accepted allowed class and refused forbidden classes and the
  no-authority set.

## Task 6 — Bounded harness
- Add `minime/local_worker/harness.py` with timeout/cancellation/cleanup, structured parse,
  deterministic-validator callback, and a corrective cap of exactly ONE local attempt.
- Completion: tests for timeout, bounded single corrective attempt, no-unbounded-retry,
  timeout cleanup and NO_CHANGE_JUSTIFIED acceptance.

## Task 7 — LocalWorkerService orchestration + evidence
- Add `minime/local_worker/service.py` that maps preflight -> eligibility -> dispatch ->
  validation -> evidence with escalation on refusal/failure/self-approval avoidance.
- Completion: unit tests producing `LocalExecutionEvidence` for a successful low-risk run.

## Task 8 — OpenSpec artifacts present & deterministic validation harness
- Ensure `openspec/changes/minimal-local-worker-bootstrap/{proposal,design,tasks}.md` and
  `specs/minimal-local-worker-bootstrap/spec.md` exist and are consistent.
- Wire deterministic validation to use scope/diff guard + ruff checks (no live Ollama).
- Completion: ruff passes, full focused test module runs, full pytest suite green when offline.

## Task 9 — Verify no authority/self-approval and clean escalation
- Add/finalize tests for the reviewer-independence + no merge authority and clean escalation
  scenarios.
- Completion: exact evidence fields asserted.

### Acceptance / failure-injection tasks
- T5 acceptance: forbidden classes never executed; evidence shows refusal + escalation.
- T6 failure-injection: simulated validator failure leads to exactly 1 corrective attempt
  then escalation, not N repeats.
