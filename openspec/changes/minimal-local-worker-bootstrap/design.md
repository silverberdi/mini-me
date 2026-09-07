# Design: Minimal Local Worker Bootstrap

## Architectural Approach
A bounded, purely additive capability that reuses existing provider/model abstractions and
keeps all execution determinism and authority in mini me core:

```
LocalTaskEnvelope ──> Eligibility Gate (allowed class + forbidden surfaces)
       |   (admitted / refused)
       v
LocalWorkerService:
  1. preflight  -> Ollama reachable + model qwen2.5-coder:7b-instruct-q4_K_M exists
  2. harness    -> bounded timeout/cancel + one corrective attempt
  3. structured output validation (Qwen never self-approves)
  4. evidence   -> provider/model/task_class/attempt/result/validation_result/escalation
  5. escalation -> existing provider policy when refused/unvalidated/uncertain/risk
```

The core makes the local verdict; Qwen only produces a constrained candidate result. This
preserves the rule that deterministic validation (scope/diff guard, ruff, targeted tests,
OpenSpec validation) remains authoritative and that a single provider/model identity never
self-reviews.

## Key Components

### 1. `local_worker/model_identity.py`
- `OLLAMA_PROVIDER` = `"ollama"`.
- `LOCAL_WORKER_ROLE` = `"local_worker"` (never reviewer/auditor/merge/approve).
- `STDLOCAL_QWEN_MODEL_IDENTITY` = `"qwen2.5-coder:7b-instruct-q4_K_M"` — exact canonical
  identity comparison helper.

### 2. `local_worker/task_classes.py`
- Canonical allowlist (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`,
  `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`).
- Forbidden-surface matchers for lifecycle/state-machine, provider-policy,
  security-sensitive, database schema/migrations, architecture, deployment/runtime
  infrastructure, destructive operations, and uncertain classification.

### 3. `local_worker/models.py` (Pydantic v2)
Deterministic task envelope, structured result (with `NO_CHANGE_JUSTIFIED` as a valid
outcome), eligibility/escalation decisions, preflight and validation result records, and a
flat execution-evidence record that captures provider, model, task class, attempt, result,
validation result and escalation.

### 4. `local_worker/ollama_adapter.py`
Thin HTTP adapter. Accepts an injected `httpx.AsyncClient`/transport so all tests run
offline (MockTransport). Reachability (`/api/tags`) and model existence (`/api/show` name
match) preflight; bounded generate; maps outcomes to `ProviderResultClass` so existing
provider-policy taxonomy is reused.

### 5. `local_worker/policy.py`
- `evaluate_eligibility`: LOW-risk admission gate. Admit only an allowlisted task class with
  no forbidden surfaces and only allowed files. Refuse/escalate otherwise with a
  deterministic `EligibilityDecision`.
- `local_worker_authorities`: enforced set proving no review/audit/merge/approve authority.
- `escalate`: clean handoff decision surfaced in evidence for the existing provider policy.

### 6. `local_worker/harness.py`
- Bounded `asyncio.wait_for` around each dispatch for timeout/cancellation semantics.
- Terminates/cancels in-flight work and performs cleanup when a deadline fires.
- Caps corrective attempts at 1; when the first validated result fails deterministic
  validation, performs exactly one bounded corrective attempt, then stops.

### 7. `local_worker/service.py`
`LocalWorkerService` orchestrates preflight -> eligibility -> dispatch -> validation ->
evidence, and never requires a live Ollama at import/collection time.

## Invariants
- Deterministic validation is authoritative; Qwen cannot approve its own result.
- Local Qwen has NO review/audit/merge/approve authority.
- Max one local corrective attempt; no unbounded retry.
- No public surface marks the local model as a reviewer or auditor.
- Clean escalation to existing provider policy is always available via a recorded decision.
- Tests require no live Ollama (injected transport).

## Rollback / Operational Notes
This change is additive and configuration-only; it does not touch scheduler, DB or
deployment runtime. It can be reverted by removing the `local_worker` package, the config
example entry and the OpenSpec change folder.
