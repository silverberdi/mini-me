# Spec: Minimal Local Worker Bootstrap

## ADDED Requirements

### Requirement: Minimal local worker bootstrap

The local worker SHALL execute only bounded LOW-risk tasks through the canonical Ollama
provider/model identity, subject to deterministic eligibility, validation, bounded retry,
escalation, and evidence rules below.

#### Scenario: Exact model identity is canonical

GIVEN the canonical local worker model identity
WHEN it is compared for exactness
THEN it SHALL equal the exact string `qwen2.5-coder:7b-instruct-q4_K_M`
AND this exact value SHALL be the single persisted/represented model identity used by the
local worker harness.

#### Scenario: Live Ollama is not required by tests

GIVEN the automated test suite for local worker bootstrap
WHEN it is collected and executed
THEN it SHALL NOT require a reachable Ollama daemon or a local model download.

#### Scenario: Unavailable Ollama fails preflight

GIVEN an environment where Ollama is not reachable
WHEN local worker preflight is evaluated
THEN preflight SHALL fail with a deterministically structured reason.

#### Scenario: Missing required model fails preflight

GIVEN Ollama is reachable but the canonical model `qwen2.5-coder:7b-instruct-q4_K_M` is not
available
WHEN local worker preflight is evaluated
THEN preflight SHALL fail with a structured reason identifying the missing model.

#### Scenario: Allowed LOW-risk task class is accepted

GIVEN a task envelope whose `task_class` is a member of
`SMALL_CODE_FIX | TEST_AUTHORING | LOG_ANALYSIS | SMALL_REFACTOR | API_SMALL_CHANGE |
UI_SMALL_POLISH`
AND whose allowed files/forbidden surfaces are consistent
WHEN the eligibility gate evaluates it
THEN it SHALL be admitted (not refused, not escalated).

#### Scenario: Forbidden / high-risk task class is rejected

GIVEN a task that touches lifecycle/state-machine, provider policy, security-sensitive
surfaces, database schema/migrations, architecture, deployment/runtime infrastructure,
destructive operations, or bears uncertain classification
WHEN the eligibility gate evaluates it
THEN it SHALL be deterministically refused with a structured reason AND routed to clean
escalation; the local worker SHALL NOT execute it.

#### Scenario: Structured output validation

GIVEN a structured local worker result
WHEN it is validated
THEN it SHALL only be accepted when it parses to the constrained schema
AND `NO_CHANGE_JUSTIFIED` SHALL be a valid, accepted outcome of the harness.

#### Scenario: Bounded timeout / failure

GIVEN a dispatched local worker task that exceeds its deadline
WHEN the deadline fires
THEN execution SHALL be cancelled, in-flight work cleaned up, and the harness SHALL record a
timeout result without spawning unlimited work.

#### Scenario: No unbounded retry; one corrective attempt

GIVEN the first structured result fails deterministic validation
WHEN a corrective pass is considered
THEN harness SHALL allow at most one local corrective attempt
AND if that corrective attempt still fails validation it SHALL stop and record escalation.

#### Scenario: Deterministic validation is authoritative / no self-approval

GIVEN a local Qwen candidate result
WHEN it is evaluated for success
THEN success SHALL be decided only by mini me deterministic validation
AND the local model (and its own result) SHALL NOT grant approval by itself.

#### Scenario: Clean escalation to existing provider policy

GIVEN a refused, unvalidated, uncertain, `escalation_required`, or authority-forbidden local
task
WHEN the worker concludes
THEN it SHALL record a structured escalation decision targeting the existing provider policy.

#### Scenario: Local Qwen has no reviewer/auditor/merge authority

GIVEN the local worker capability
WHEN its authorities are enumerated
THEN it SHALL grant NO review, audit, merge, or approve authority to local Qwen
AND such roles SHALL remain absent from its supported role set.

#### Scenario: Execution evidence is minimal and structured

GIVEN a completed local worker run
WHEN evidence is emitted
THEN it SHALL contain at least: provider (`ollama`), canonical model identity, task class,
attempt number, result class, validation result, and escalation decision.
