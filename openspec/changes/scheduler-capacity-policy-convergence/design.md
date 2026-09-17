## Context

The scheduler sits at the boundary between persisted work backlog and autonomous execution pipelines. Its core mandate is to answer:
> *"Given the current backlog/job and current provider/reviewer capacity truth, may mini me safely admit and execute work now?"*

Prior iterations and historical drafts introduced ambiguity where admission decisions relied on static or configured defaults rather than runtime provider health, checked only implementer availability while neglecting reviewer capacity and model independence, conflated post-execution outcomes (like harness crashes or insufficient editing evidence) with pre-admission capacity waits, allowed unproductive paid retry loops for incapable providers, and introduced an ad-hoc fifth decision (`REFUSED`) that blurred the line between scheduler capacity decisions and downstream execution outcomes.

This design reconciles and converges scheduler capacity and admission policy into a single, authoritative, fail-closed policy engine.

## Goals / Non-Goals

**Goals:**
- **Authoritative Runtime Capacity Truth**: Admission decisions evaluate live provider health, cooldowns, and quota states via `ProviderHealthService`, never relying solely on static configuration.
- **Safe Executable Pair Requirement (`SAFE_EXECUTABLE_PAIR_EXISTS`)**: Work is admitted (`RUN`) only when both an eligible implementer AND a compatible, independent reviewer are healthy and available right now.
- **Strict Drain Policy**: Drain fallback (OpenRouter) is strictly confined to finishing active in-flight executions and is blocked from admitting new work.
- **Pre-Admission vs Post-Execution Separation**: Distinguish pre-admission observable states from post-execution attempt outcomes.
- **Zero Unproductive Retries on `EVIDENCE_INSUFFICIENT`**: Enforce that textual/provider success without verifiable repository-editing evidence maps immediately to `NEEDS_HUMAN` on subsequent scheduling, with zero automatic retries and zero capacity wait.
- **Strict Human Gate vs Predecessor Wait Separation**: Explicit human approval/merge gates map strictly to `NEEDS_HUMAN`, while automated predecessor/dependency progression maps to `WAIT`.
- **Unified 4-Decision Taxonomy**: Restrict scheduler operational decisions strictly to `RUN`, `DRAIN`, `WAIT`, and `NEEDS_HUMAN`. Remove `REFUSED` from capacity decisions.
- **Epistemic Honesty**: Cooldowns and wait states must be grounded in observable telemetry or explicit provider reset signals; no fabricated recovery ETAs.
- **Single Converged Engine**: CLI commands, REST endpoints (`/api/v1/scheduler/tick`), TUI actions, and background daemon loops invoke identical evaluation logic in `SchedulerService.evaluate_admission`.

**Non-Goals:**
- Implementing dynamic AI model/provider routing, complexity-weighted capability selection, or adaptive scoring (owned by later changes).
- Ranking providers, selecting the "best" pair, or reserving future provider capacity during admission.
- Re-architecting provider health tracking or replacing PostgreSQL persistence.
- Modifying `ModelIndependencePolicy` rules or allowing same-model review in primary tier.
- Bypassing human merge or validation gates.

---

## Architectural Decisions

### D1: Standardized 4-Decision Operational Taxonomy (Resolving `REFUSED`)

Scheduler operational capacity decisions are strictly confined to four mutually exclusive outcomes:

| Decision | Definition | Permitted Next Action |
|---|---|---|
| `RUN` | Backlog item is ready and a safe executable pair exists (`SAFE_EXECUTABLE_PAIR_EXISTS`). | Claim work and launch execution attempt. |
| `DRAIN` | Primary capacity is exhausted, but an active in-flight run is eligible for budgeted drain fallback. | Permit active attempt continuation; reject new admissions. |
| `WAIT` | Backlog item is valid, but temporarily blocked by provider cooldown, active probe lock, or pending predecessor stage / automated dependency. | Retain item in queue; re-evaluate on next tick or probe expiry. |
| `NEEDS_HUMAN` | Execution is blocked by missing credentials, invalid configuration, permanent model-independence impossibility, insufficient repository-editing evidence, or required human gate/approval. | Surface blocker to operator; do not auto-retry. |

**Resolution of `REFUSED`**:
- In the existing codebase, `AdmissionDecision.REFUSED` is a broad legacy bucket in `src/minime/domain/enums.py:533` paired with `AdmissionRefusalCode` to represent any non-admitted state.
- In this converged policy, `REFUSED` is **REMOVED** as a standalone scheduler capacity decision.
- Operational evaluation maps every non-RUN outcome to either `WAIT` (when automatically recoverable via provider probe or predecessor completion) or `NEEDS_HUMAN` (when human intervention, approval gate, or configuration fix is required).
- Downstream execution and validation outcomes (e.g. `EVIDENCE_INSUFFICIENT`, `HARNESS_UNAVAILABLE`, `LOCAL_RUNTIME_FAILURE`) remain strictly **post-execution outcome classifications** on `job_attempts`, rather than scheduler capacity decisions.

---

### D2: Safe Executable Pair Semantics (`SAFE_EXECUTABLE_PAIR_EXISTS`)

Autonomous execution requires both implementation and independent authoritative review. The scheduler evaluates executability, not preference or ranking.

**Definition of `SAFE_EXECUTABLE_PAIR_EXISTS`**:
There exists at least one eligible implementer provider $I$ and at least one candidate reviewer provider $R$ such that:
1. $I$ is configured, authenticated, and currently reports `AVAILABLE` or `DEGRADED` (not in active cooldown) in `ProviderHealthService`.
2. $R$ satisfies `ModelIndependencePolicy` with respect to $I$ (distinct primary provider/model family in primary tier; distinct model identity in drain).
3. $R$ is configured, authenticated, and currently reports `AVAILABLE` or `DEGRADED` (not in active cooldown) in `ProviderHealthService`.

**Evaluation Rules**:
- **Executability, Not Selection**: The scheduler verifies only that $\ge 1$ safe pair exists right now. It does NOT rank pairs, compute preference scores, select the "best" pair, or reserve capacity.
- **Reviewer Healthy NOW**: Candidate reviewer capacity must be available at admission time. The scheduler does not speculate that a reviewer will recover while implementation runs.
- **Temporary Reviewer Exhaustion -> `WAIT`**: If an implementer is available but all compatible independent reviewers are in cooldown, emit `WAIT` with condition `CAPACITY_EXHAUSTED`.
- **Structural Impossibility -> `NEEDS_HUMAN`**: If the configured provider set cannot satisfy `ModelIndependencePolicy` under any circumstances (e.g. single model family configured), emit `NEEDS_HUMAN` with condition `REVIEWER_INDEPENDENCE_UNAVAILABLE`.
- **UNKNOWN Reviewer Capacity**: If reviewer health is unknown but an automated probe is scheduled/active, emit `WAIT` with `has_deterministic_eta=False`. If no automated probe path exists, emit `NEEDS_HUMAN`.

---

### D3: Strict Drain Policy & Runtime Authority

OpenRouter is the canonical bounded drain fallback in the codebase, governed by:
- `src/minime/services/openrouter_eligibility.py` (`OpenRouterEligibilityEvaluator`, `is_material_execution_started`)
- `src/minime/services/budget_service.py` (`BudgetService`, `BudgetHeadroom`)
- `src/minime/domain/models.py` (`OpenRouterBudgetPolicy`)

**Rules**:
- `DRAIN` is strictly an in-flight continuation mode for jobs where material execution has already started (`attempt_count > 0` or candidate SHA produced) and primary subscriptions are exhausted.
- `DRAIN` is **NEVER** an admission permission for new `READY` backlog items. When primaries are exhausted, new items evaluate to `WAIT` (if primaries are in transient cooldown) or `NEEDS_HUMAN` (if primaries are unconfigured/expired). A new work item must not enter execution merely because drain fallback exists.
- During drain fallback, implementer and reviewer must have distinct model identities (`model_identity_service.py`).
- If remaining drain budget headroom is zero, in-flight execution halts with `NEEDS_HUMAN` (`BUDGET_EXCEEDED`).

---

### D4: Pre-Admission vs Post-Execution Separation & Settled Evidence Truth

The scheduler distinguishes what is observable **before admission** from what is only discovered **after execution**:

1. **Pre-Admission Observables**: Provider health status, probe locks, cooldown timestamps, API credential presence, project binding validity, and change readiness status (`DoR`).
2. **Post-Execution Outcomes**: Process crashes (`LOCAL_RUNTIME_FAILURE`), uninstalled tool binaries (`HARNESS_UNAVAILABLE`), missing test/diff evidence (`EVIDENCE_INSUFFICIENT`), and token timeouts.
3. **Settled Evidence Contract for `EVIDENCE_INSUFFICIENT`**:
   - In accordance with the canonical provider execution stabilization contract, textual/provider output that claims success without sufficient repository-editing evidence produces `EVIDENCE_INSUFFICIENT`.
   - On subsequent scheduler admission evaluation, `EVIDENCE_INSUFFICIENT` maps strictly to `NEEDS_HUMAN`.
   - **NO automatic corrective retry** is permitted.
   - **NO capacity cooldown wait** is permitted merely because retry budget numerically remains.
   - **NO repeated paid incapable invocations** may be executed.
4. **Human Gate vs Predecessor Wait**:
   - Automated predecessor / dependency progression maps to `WAIT` (automatically recoverable when predecessor finishes).
   - Explicit human gates (`HUMAN_APPROVAL_REQUIRED`, manual approval, container preview validation, manual merge) map strictly to `NEEDS_HUMAN`.

---

### D5: Epistemic Honesty in Recovery Timers

- **Deterministic Upstream Headers**: When a provider returns an explicit `Retry-After` or rate limit reset timestamp, `cooldown_until` is set to that exact value and `has_deterministic_eta=True`.
- **Indeterminate Wait**: When quota is exhausted without an explicit reset header, the scheduler applies exponential backoff probe intervals, records `has_deterministic_eta=False`, and displays indeterminate wait status without fabricating an ETA.
- **Probe Lock Enforcement**: Active cooldown windows lock out automated API probes until the cooldown interval expires, preventing rate-limit thrashing.
- **Invariant**: `UNKNOWN MUST NEVER BECOME RUN`. If provider capacity or evidence completeness is unknown, the scheduler fails closed to `WAIT` (if auto-probe active) or `NEEDS_HUMAN`.

---

### D6: Single Converged Authority

All execution pathways delegate to the single canonical method:
- **Canonical Symbol**: `SchedulerService.evaluate_admission(project_id, change_name)` in `src/minime/services/scheduler_service.py:205` (and orchestrator entry point `SchedulerService.tick(project_id)` in line 700).
- **Delegating Interfaces**:
  1. CLI: `minime scheduler tick` (`src/minime/cli/main.py:700`)
  2. REST API: `POST /api/v1/scheduler/tick` (`src/minime/api/app.py:1897`)
  3. TUI: Queue view tick action (`src/minime/tui/views/queue.py`)
  4. Daemon: Background loop in `minime-scheduler.service`

No caller may implement private admission checks or bypass `SAFE_EXECUTABLE_PAIR_EXISTS`.

---

## Normative Failure Taxonomy Table

| Condition | Observation Stage | Scheduler Decision | Human Required? | Automatically Recoverable? | Retry Condition | Capacity-Related? | Notes |
|---|---|---|---|---|---|---|---|
| `CAPACITY_EXHAUSTED` | `PRE_ADMISSION_OBSERVABLE` | `WAIT` (or `DRAIN` only for already-admitted in-flight work) | No | Yes | Cooldown expires / probe confirms recovery | Yes | Primary quota/rate limit reached; deterministic or backoff cooldown. |
| `AUTH_REQUIRED` | `PRE_ADMISSION_OBSERVABLE` or `BOTH` | `NEEDS_HUMAN` | Yes | No | None (operator must supply valid API keys) | No | Missing or rejected credentials; never enters auto-cooldown. |
| `CONFIGURATION_INVALID` | `PRE_ADMISSION_OBSERVABLE` | `NEEDS_HUMAN` | Yes | No | None (operator must fix project/model config) | No | Malformed yaml, invalid repository binding, or missing model definition. |
| `HARNESS_UNAVAILABLE` (Structural) | `PRE_ADMISSION_OBSERVABLE` or `POST_EXECUTION_OUTCOME` | `NEEDS_HUMAN` | Yes | No | None (operator must install/configure harness tools) | No | Missing local tool binary (e.g. git, compiler, test runner). |
| `HARNESS_UNAVAILABLE` (Transient) | `POST_EXECUTION_OUTCOME` | `WAIT` | No | Yes | Transient worker process restart | No | Bounded retry if worker restart mechanism is available. |
| `PROVIDER_UNAVAILABLE` | `PRE_ADMISSION_OBSERVABLE` | `WAIT` (if transient) / `NEEDS_HUMAN` (if permanent) | No / Yes | Yes (if transient network) / No (if unreachable endpoint) | Network probe succeeds or backoff timer expires | Partial | Network outage, DNS failure, or 5xx provider outage. |
| `EVIDENCE_INSUFFICIENT` | `POST_EXECUTION_OUTCOME` | `NEEDS_HUMAN` | Yes | No | None until human/config/harness correction creates new evidence | No | Textual/provider success without verifiable repo-editing evidence. Zero auto-retry; zero capacity wait; no repeated paid incapable invocation. |
| `REVIEWER_INDEPENDENCE_UNAVAILABLE` (Transient) | `PRE_ADMISSION_OBSERVABLE` | `WAIT` | No | Yes | Independent reviewer recovers from cooldown | Yes | Implementer available, but all valid independent reviewers in cooldown. |
| `REVIEWER_INDEPENDENCE_UNAVAILABLE` (Structural) | `PRE_ADMISSION_OBSERVABLE` | `NEEDS_HUMAN` | Yes | No | None (operator must configure complementary provider) | No | Configured provider pool cannot satisfy ModelIndependencePolicy. |
| `LOCAL_RUNTIME_FAILURE` | `POST_EXECUTION_OUTCOME` | `NEEDS_HUMAN` (if fatal) / `WAIT` (if retryable) | Yes / No | No (if disk full/oom) / Yes (if transient error) | Bounded retry counter < MAX_ATTEMPTS | No | Process crash, OS error, or subprocess execution failure. |
| `LIFECYCLE_BLOCKED` (Predecessor) | `PRE_ADMISSION_OBSERVABLE` | `WAIT` | No | Yes | Predecessor roadmap change completes (DONE) | No | Earlier roadmap stage or dependency is progressing autonomously. |
| `LIFECYCLE_BLOCKED` (Invalid Spec) | `PRE_ADMISSION_OBSERVABLE` | `NEEDS_HUMAN` | Yes | No | None (operator must fix OpenSpec artifacts) | No | Change violates OpenSpec schema or strict validation rules. |
| `HUMAN_APPROVAL_REQUIRED` | `PRE_ADMISSION_OBSERVABLE` | `NEEDS_HUMAN` | Yes | No | Operator approval granted | No | Project configured with `auto_admit=False`, container preview validation required, or manual merge gate. |
| `UNKNOWN_CAPACITY` (Probeable) | `PRE_ADMISSION_OBSERVABLE` | `WAIT` | No | Yes | Background probe execution returns health status | Yes | Initial startup or unmeasured provider; probe active. |
| `UNKNOWN_CAPACITY` (Unprobeable) | `PRE_ADMISSION_OBSERVABLE` | `NEEDS_HUMAN` | Yes | No | None (operator intervention required) | Yes | Provider state cannot be determined and no automated probe exists. |

---

## Domain Models & Interfaces

```python
class AdmissionDecisionKind(str, Enum):
    RUN = "RUN"
    DRAIN = "DRAIN"
    WAIT = "WAIT"
    NEEDS_HUMAN = "NEEDS_HUMAN"

class AdmissionBlockCondition(str, Enum):
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    HARNESS_UNAVAILABLE = "HARNESS_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    REVIEWER_INDEPENDENCE_UNAVAILABLE = "REVIEWER_INDEPENDENCE_UNAVAILABLE"
    LOCAL_RUNTIME_FAILURE = "LOCAL_RUNTIME_FAILURE"
    LIFECYCLE_BLOCKED = "LIFECYCLE_BLOCKED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    UNKNOWN_CAPACITY = "UNKNOWN_CAPACITY"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

class AdmissionEvaluationResult(BaseModel):
    decision: AdmissionDecisionKind
    project_id: str
    change_name: str
    safe_executable_pair_exists: bool
    eligible_implementer: str | None = None
    eligible_reviewer: str | None = None
    block_condition: AdmissionBlockCondition | None = None
    rationale: str
    cooldown_until: datetime | None = None
    has_deterministic_eta: bool = False
    evidence_complete: bool = True
```

---

## Historical Policy Supersession

`provider-capacity-drain-policy` is explicitly designated as **SUPERSEDED / DO_NOT_IMPLEMENT**.
- All overlapping scheduler admission and capacity evaluation requirements are formally replaced by `scheduler-capacity-policy-convergence`.
- Existing landed implementations of OpenRouter drain fallback (`openrouter_eligibility.py`, `budget_service.py`) and provider health tracking (`provider_health_service.py`) remain authoritative and are consumed as dependencies by this change.
