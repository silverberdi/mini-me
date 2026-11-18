# scheduler-capacity-policy-convergence Specification

## Purpose
Converge and unify scheduler capacity evaluation and admission policy against live runtime provider health, safe executable pair verification (`SAFE_EXECUTABLE_PAIR_EXISTS`), strict drain isolation, zero unproductive retries on insufficient editing evidence, and precise pre-admission vs post-execution failure classification.

## Requirements

### Requirement: Four-Decision Operational Taxonomy
The scheduler SHALL evaluate admission into exactly one of four operational decisions: `RUN`, `DRAIN`, `WAIT`, or `NEEDS_HUMAN`. The scheduler SHALL NOT emit `REFUSED` as a standalone capacity decision. Post-execution outcome states SHALL remain distinct classifications on execution attempts and SHALL NOT be conflated with pre-admission capacity decisions.

#### Scenario: Admission emits RUN when safe executable pair exists
- **WHEN** a backlog item is in `READY` lifecycle status
- **AND** `SAFE_EXECUTABLE_PAIR_EXISTS` evaluates to `True`
- **THEN** the operational decision SHALL be `RUN`
- **AND** execution attempt creation SHALL be permitted

#### Scenario: Admission emits WAIT on temporary capacity cooldown
- **WHEN** a backlog item is in `READY` lifecycle status
- **AND** implementer or candidate independent reviewers are in active capacity cooldown
- **THEN** the operational decision SHALL be `WAIT`
- **AND** block condition SHALL be `CAPACITY_EXHAUSTED`
- **AND** the item SHALL remain in queue for automated re-evaluation

#### Scenario: Admission emits NEEDS_HUMAN on structural auth or config failure
- **WHEN** provider credentials are missing or project configuration is invalid
- **THEN** the operational decision SHALL be `NEEDS_HUMAN`
- **AND** block condition SHALL be `AUTH_REQUIRED` or `CONFIGURATION_INVALID`
- **AND** automated retry SHALL be suspended until operator intervention

### Requirement: Safe Executable Pair Verification (`SAFE_EXECUTABLE_PAIR_EXISTS`)
The scheduler SHALL admit a backlog item (`RUN`) if and only if `SAFE_EXECUTABLE_PAIR_EXISTS` is `True`, meaning there exists at least one currently eligible implementer provider AND at least one currently eligible independent reviewer provider satisfying `ModelIndependencePolicy` and reporting `AVAILABLE` or `DEGRADED` in `ProviderHealthService`. The scheduler SHALL NOT rank providers, select preferred pairs, reserve capacity, or perform capability selection.

#### Scenario: Both implementer and independent reviewer healthy admits work
- **WHEN** an eligible implementer is healthy and not in cooldown
- **AND** an independent reviewer satisfying `ModelIndependencePolicy` is healthy and not in cooldown
- **THEN** `SAFE_EXECUTABLE_PAIR_EXISTS` SHALL be `True`
- **AND** the operational decision SHALL be `RUN`

#### Scenario: Implementer healthy but all independent reviewers in cooldown yields WAIT
- **WHEN** an eligible implementer is healthy
- **AND** all candidate reviewer providers satisfying model independence are currently in cooldown or exhausted
- **THEN** `SAFE_EXECUTABLE_PAIR_EXISTS` SHALL be `False`
- **AND** the operational decision SHALL be `WAIT`
- **AND** block condition SHALL be `REVIEWER_INDEPENDENCE_UNAVAILABLE` with capacity-related flag set to `True`

#### Scenario: Model independence structurally impossible yields NEEDS_HUMAN
- **WHEN** configured provider pool cannot satisfy `ModelIndependencePolicy` under any circumstances
- **THEN** `SAFE_EXECUTABLE_PAIR_EXISTS` SHALL be `False`
- **AND** the operational decision SHALL be `NEEDS_HUMAN`
- **AND** block condition SHALL be `REVIEWER_INDEPENDENCE_UNAVAILABLE` with capacity-related flag set to `False`

#### Scenario: Unknown reviewer capacity with active probe yields WAIT
- **WHEN** reviewer capacity status is `UNKNOWN` but an automated health probe is scheduled or in progress
- **THEN** the operational decision SHALL be `WAIT`
- **AND** block condition SHALL be `UNKNOWN_CAPACITY`
- **AND** `has_deterministic_eta` SHALL be `False`

### Requirement: Pre-Admission vs Post-Execution Separation & Settled Evidence Truth
The scheduler SHALL distinguish pre-admission observable conditions from post-execution attempt outcomes. Textual/provider success lacking sufficient repository-editing evidence SHALL produce `EVIDENCE_INSUFFICIENT` and require human intervention without automated retry.

#### Scenario: Structural harness absence yields NEEDS_HUMAN
- **WHEN** a local execution tool binary or required harness executable is uninstalled or missing
- **THEN** the condition SHALL be classified as structural `HARNESS_UNAVAILABLE`
- **AND** the operational decision SHALL be `NEEDS_HUMAN`
- **AND** no capacity cooldown SHALL be triggered

#### Scenario: Transient harness crash allows bounded retry
- **WHEN** a local worker process crashes transiently during execution
- **AND** attempt retry budget remains available
- **THEN** the post-execution outcome SHALL be recorded as `LOCAL_RUNTIME_FAILURE`
- **AND** subsequent scheduler evaluation SHALL permit retry (`WAIT` or `RUN` based on worker restart state)

#### Scenario: Insufficient repository-editing evidence maps strictly to NEEDS_HUMAN
- **WHEN** a provider execution produces textual output claiming success without verifiable repository-editing evidence (`EVIDENCE_INSUFFICIENT`)
- **THEN** the subsequent admission evaluation SHALL emit `NEEDS_HUMAN` with block condition `EVIDENCE_INSUFFICIENT`
- **AND** the system SHALL NOT perform an automatic corrective retry
- **AND** the system SHALL NOT enter a capacity cooldown wait
- **AND** the system SHALL NOT invoke repeated paid incapable provider attempts

#### Scenario: Predecessor progression yields WAIT
- **WHEN** a change is blocked awaiting completion of an earlier roadmap stage or declared dependency
- **THEN** the operational decision SHALL be `WAIT` with block condition `LIFECYCLE_BLOCKED`

#### Scenario: Explicit human gate yields NEEDS_HUMAN
- **WHEN** a change is blocked awaiting human approval, container preview validation, or manual merge
- **THEN** the operational decision SHALL be `NEEDS_HUMAN` with block condition `HUMAN_APPROVAL_REQUIRED`

#### Scenario: Invalid OpenSpec artifacts yield NEEDS_HUMAN
- **WHEN** a change violates OpenSpec schema or strict validation rules
- **THEN** the operational decision SHALL be `NEEDS_HUMAN` with block condition `LIFECYCLE_BLOCKED`

### Requirement: Epistemic Honesty in Recovery Timers
The system SHALL NOT generate fabricated ETAs or arbitrary recovery timestamps when provider capacity reset times are unknown. `UNKNOWN` capacity MUST NEVER be evaluated as `RUN`.

#### Scenario: Deterministic reset header sets cooldown timestamp
- **WHEN** an upstream provider returns an explicit `Retry-After` or reset header
- **THEN** `cooldown_until` SHALL be set to that exact timestamp
- **AND** `has_deterministic_eta` SHALL be `True`

#### Scenario: Unknown reset interval reports indeterminate wait
- **WHEN** a provider exhausts quota without returning an explicit reset timestamp
- **THEN** exponential backoff probe intervals SHALL be applied
- **AND** `has_deterministic_eta` SHALL be `False`
- **AND** no speculative completion ETA SHALL be displayed

#### Scenario: Active cooldown window locks automated probes
- **WHEN** a provider is in an active cooldown window
- **THEN** automated API probe requests SHALL be locked until the cooldown window expires

### Requirement: Single Converged Admission Authority
All system interfaces (CLI `minime scheduler tick`, REST API `POST /api/v1/scheduler/tick`, TUI queue view, and daemon `minime-scheduler.service`) SHALL execute the exact same admission logic via `SchedulerService.evaluate_admission`.

#### Scenario: CLI tick delegates to single authority
- **WHEN** an operator invokes `minime scheduler tick`
- **THEN** admission SHALL be evaluated via `SchedulerService.evaluate_admission` in `src/minime/services/scheduler_service.py`

#### Scenario: REST API tick delegates to single authority
- **WHEN** an HTTP request is received at `POST /api/v1/scheduler/tick`
- **THEN** admission SHALL be evaluated via `SchedulerService.evaluate_admission` in `src/minime/services/scheduler_service.py`

#### Scenario: Background daemon delegates to single authority
- **WHEN** the background scheduler service runs its tick cycle
- **THEN** admission SHALL be evaluated via `SchedulerService.evaluate_admission` in `src/minime/services/scheduler_service.py` without private bypasses

### Requirement: In-flight fallback eligibility is independent of internal spend caps
The scheduler SHALL evaluate configured fallback eligibility using provider role/configuration, actual provider capacity evidence, and in-flight pipeline state; it SHALL NOT require an internal daily/monthly budget cap, budget-policy row, or headroom calculation. It SHALL keep new READY work out of the rescue path and preserve the required DRAIN/WAIT and role-separation rules.

#### Scenario: In-flight execution continues without a legacy cap policy
- **WHEN** a materially started execution is in the permitted drain state, required primary providers are verified unavailable, and a fallback profile is configured
- **THEN** the scheduler allows the configured fallback decision without testing local daily/monthly headroom

#### Scenario: New ready work remains excluded
- **WHEN** a new READY item is evaluated while rescue fallback is available
- **THEN** the scheduler does not admit that item through the in-flight fallback path

#### Scenario: Provider capacity is unknown
- **WHEN** required primary-provider capacity cannot be verified
- **THEN** the scheduler follows the existing fail-safe WAIT or human decision path and does not infer that a spend cap caused the block

#### Scenario: Fallback profile is unavailable
- **WHEN** the permitted in-flight path is reached but no configured fallback profile or credentials are available
- **THEN** the scheduler reports that exact provider configuration gap and preserves the in-flight state
