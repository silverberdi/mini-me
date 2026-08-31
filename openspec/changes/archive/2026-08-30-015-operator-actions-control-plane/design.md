# Design: Operator Actions Control Plane

## Architecture Overview

The Operator Control Plane is the single canonical mutation boundary in mini me. Presentation layers (TUI, CLI, and future PWA) do not execute business logic, run arbitrary shell commands, or perform direct unvalidated state mutations.

```text
       +------------------+------------------+
       |                  |                  |
   Textual TUI           CLI             future PWA
       |                  |                  |
       +------------------+------------------+
                          |
                          v (Typed Action Requests)
           +------------------------------+
           | Operator Control Plane       |
           | - Action Discovery           |
           | - Optimistic Concurrency     |
           | - Authority Validation       |
           | - Idempotency Guardian       |
           | - Action Audit Persistence   |
           +------------------------------+
                          |
                          v (Governed Domain Invocations)
       +------------------+------------------+
       |                  |                  |
 Orchestration      Preview/Validation   Recovery / Health
       |                  |                  |
       v                  v                  v
  PostgreSQL             Docker             Git Worktrees
```

## Domain Models and Contracts

### 1. `OperatorActionType` (Enum)
- `CONTINUE` / `RESUME`: Continue stopped run or resume from checkpoint.
- `RETRY`: Rerun failed check or transient provider failure.
- `REASSIGN`: Reassign run to compatible alternative implementer/reviewer.
- `RESOLVE_GATE`: Resolve a specific `NEEDS_HUMAN` gate (e.g. preserved candidate conflict, UI validation).
- `CANCEL`: Safely stop an active run.
- `START_PREVIEW`: Start/build container preview for candidate.
- `TEARDOWN_PREVIEW`: Stop and clean up container preview.
- `RECOVER_LOCKS`: Clean up abandoned Git locks with verified ownership.

### 2. `OperatorActionStatus` (Enum)
- `ACCEPTED`: Request validated and queued/dispatched for execution.
- `COMPLETED`: Action executed successfully to completion.
- `REJECTED`: Action not permitted from current state or authority check failed.
- `FAILED`: Action was accepted but execution encountered an internal failure.
- `BLOCKED`: Action cannot progress due to external policy or provider unavailability.

### 3. `OperatorActionErrorCode` (Enum)
- `ACTION_NOT_ALLOWED`: Action illegal from current run state.
- `STALE_OPERATOR_STATE`: Optimistic concurrency check failed (state changed since operator view loaded).
- `AUTHORITY_MISMATCH`: Target run, project, or candidate authority does not match request.
- `PROVIDER_UNAVAILABLE`: Target provider exhausted or in cooldown.
- `BUDGET_BLOCKED`: OpenRouter or project budget exceeded.
- `RECOVERY_REQUIRED`: System requires recovery reconciliation before action can proceed.
- `ACTION_ALREADY_COMPLETED`: Request ID already executed.
- `INVALID_ACTION_PARAMETERS`: Missing or malformed parameters.
- `ACTION_EXECUTION_FAILED`: Internal execution failure during action dispatch.

### 4. `OperatorActionRequest` (Pydantic / Domain Model)
```python
class OperatorActionRequest(BaseModel):
    action_request_id: str  # Unique idempotency UUID
    project_id: str
    change_name: str
    run_id: str
    action_type: OperatorActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    actor_identity: str = "operator"  # "operator", "system", "agent"
    source_interface: str = "tui"  # "tui", "cli", "pwa", "api"
    expected_stage: OrchestrationStage | None = None
    expected_generation: int | None = None
    expected_candidate_sha: str | None = None
    expected_human_gate: HumanGate | None = None
    requested_at: datetime = Field(default_factory=utc_now)
```

### 5. `OperatorActionResult` (Pydantic / Domain Model)
```python
class OperatorActionResult(BaseModel):
    action_request_id: str
    action_type: OperatorActionType
    status: OperatorActionStatus
    error_code: OperatorActionErrorCode | None = None
    summary: str
    resulting_stage: OrchestrationStage | None = None
    resulting_outcome: OrchestrationStopOutcome | None = None
    resulting_gate: HumanGate | None = None
    evidence_reference: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)
```

### 6. `OperatorActionRecord` (Database Entity & Model)
Persisted in table `operator_action_records`:
- `action_record_id` (UUID PK)
- `action_request_id` (UUID, unique index)
- `project_id` (String)
- `change_name` (String)
- `run_id` (String, indexed)
- `action_type` (String)
- `actor_identity` (String)
- `source_interface` (String)
- `precondition_stage` (String)
- `precondition_gate` (String, nullable)
- `status` (String)
- `error_code` (String, nullable)
- `summary` (Text)
- `resulting_stage` (String, nullable)
- `resulting_gate` (String, nullable)
- `parameters_json` (JSONB)
- `result_payload_json` (JSONB)
- `created_at` (Timestamp UTC)

## Action Discovery Contract

`ActionDescriptor`:
- `action`: `OperatorActionType`
- `display_name`: Human-readable label
- `description`: Action explanation
- `enabled`: Boolean
- `disabled_reason`: Explanation if `enabled == False`
- `requires_confirmation`: Boolean
- `confirmation_prompt`: Text explaining consequence if confirmed
- `risk_level`: `LOW` | `MEDIUM` | `HIGH`
- `parameters_schema`: JSON schema describing required parameters

## Acceptance Matrix

| Action | Valid Source States / Gates | Invalid Source States | Authority Requirements | Idempotency Contract | Resulting State |
|---|---|---|---|---|---|
| `CONTINUE` / `RESUME` | Stopped runs with `resumable_stage != None`, `STOPPED_AT_GATE` | Active running runs (`is_active == True`), terminal `MERGED`/`DONE` | Run must exist; project registered | Return existing active run status if already resumed | Active run advanced to target stage |
| `RETRY` | Failed checks (`RUNNING_CHECKS` failure), transient provider failure | Successful runs, running stages | Provider capacity available, retry counter < max | Return same retry outcome if duplicate request ID | Target stage restarted with incremented attempt |
| `REASSIGN` | Provider exhausted/unavailable, review remediation failed | Running execution, non-reassignable gate | Compatible alternative provider configured; model independence respected | Return existing handoff/run if duplicate request ID | Executor reassigned, handoff recorded |
| `RESOLVE_GATE` (`continue_preserved`) | `PRESERVED_CANDIDATE_INTEGRATION_CONFLICT` | Runs without gate, other gate types | Preserved candidate exists, base SHA matches | Return resolved run status | Run advances past gate to next stage |
| `RESOLVE_GATE` (`remediate_preserved`) | `PRESERVED_CANDIDATE_INTEGRATION_CONFLICT` | Runs without gate | Remediation contract provided and valid | Return remediated run generation | New generation started in `IMPLEMENTING` |
| `RESOLVE_GATE` (`submit_validation`) | `UI_VALIDATION_REQUIRED` | Runs without validation gate | Valid candidate head SHA + base SHA + image digest | Return validation session status | Gate cleared, run advances to `PREPARING_PR` |
| `CANCEL` | Any active run (`is_active == True`) in non-terminal stage | Already stopped or terminal runs | Run exists | Return cancelled run status | `is_active=False`, `stop_outcome=CANCELLED`, preview torn down |
| `START_PREVIEW` | Candidate frozen, preview contract configured | Missing candidate, invalid compose | Project preview config valid | Return existing active preview session | Preview status `READY` / `RUNNING` |
| `TEARDOWN_PREVIEW` | Active preview session exists | No active preview | Ownership matches run/project | Return torn-down status | Preview status `STOPPED` |

## Safety & Governance Principles

1. **Optimistic Concurrency**:
   - If caller supplies `expected_stage`, `expected_generation`, `expected_candidate_sha`, or `expected_human_gate`, control plane verifies match before state mutation.
   - On mismatch, immediately returns `REJECTED` with code `STALE_OPERATOR_STATE`.
2. **Deterministic Idempotency**:
   - Every mutating call checks `operator_action_records` by `action_request_id`.
   - If record exists, returns stored result immediately without mutating state or re-dispatching side effects.
3. **Cancellation Safety**:
   - Active provider subprocesses/tasks are cancelled cleanly.
   - Worktree and Git refs are preserved untouched.
   - Candidate generation, review findings, and audit evidence remain immutable.
   - Owned container preview resources are torn down cleanly.
4. **Secret Sanitization**:
   - Action parameters and results are passed through `redact_secrets()`.
   - No API tokens, private keys, or credentials stored in `parameters_json` or `result_payload_json`.
5. **No God Mode / Bypasses**:
   - No action allows direct database modification, skipping review/audit requirements, or force-merging PRs.
