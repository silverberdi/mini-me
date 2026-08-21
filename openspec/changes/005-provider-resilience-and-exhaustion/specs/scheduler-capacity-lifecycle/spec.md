## Purpose

Manages scheduler capacity lifecycle modes (`RUN`, `DRAIN`, `WAIT`) and enforces strict primary-pair admission control and in-flight job preservation.

## ADDED Requirements

### Requirement: Primary-driven scheduler mode state machine
The system SHALL operate the scheduler under three explicit modes: `RUN`, `DRAIN`, and `WAIT`, driven strictly by the availability of configured primary execution providers (Codex and Antigravity).

#### Scenario: Normal RUN mode operation
- **WHEN** all required primary provider roles for the project's configured pair (implementer AND reviewer) are verified available
- **THEN** the scheduler operates in `RUN` mode, admitting new `READY` changes and executing active pipelines.

#### Scenario: Transition to DRAIN when any required primary role is unavailable
- **WHEN** any required primary role in the configured pair is exhausted or unavailable (e.g. Codex is available but Antigravity is exhausted, or the reverse)
- **THEN** the scheduler transitions from `RUN` to `DRAIN`, logs a `SCHEDULER_MODE_CHANGED` event, and halts admission of new `READY` changes.

#### Scenario: In-flight execution during DRAIN mode
- **WHEN** the scheduler is in `DRAIN` mode and an in-flight job reaches a phase whose specific primary provider is currently available (e.g. Codex implementation while Antigravity is exhausted)
- **THEN** the scheduler allows that specific phase to execute and advance until it reaches an unavailable provider phase.

#### Scenario: Transition to WAIT when no primary work can progress
- **WHEN** the scheduler is in `DRAIN` mode and no active in-flight job can make safe progress due to primary provider unavailability
- **THEN** the scheduler transitions to `WAIT`, pauses pipeline polling, and logs a `SCHEDULER_MODE_CHANGED` event.

#### Scenario: Deterministic return to RUN upon verified pair recovery
- **WHEN** the scheduler is in `WAIT` or `DRAIN` mode and positive probe evidence confirms that all required roles in the primary pair are verified available
- **THEN** the scheduler transitions to `RUN` and resumes normal work admission.

#### Scenario: DeepSeek audit availability does not drive primary scheduler mode
- **WHEN** DeepSeek Direct experiences a transient error or rate limit
- **THEN** the system handles the audit failure within the 004 audit lifecycle and SHALL NOT cause a scheduler transition to `DRAIN` or `WAIT`.

### Requirement: Strict admission control for READY work
The system SHALL admit a new `READY` change ONLY when all required primary roles for the configured pair have verified availability in `RUN` mode, and SHALL strictly prohibit admission during `DRAIN` or `WAIT` modes.

#### Scenario: New READY change admission blocked in DRAIN mode
- **WHEN** a change reaches `READY` status while the scheduler is in `DRAIN` mode (even if the implementer is available but reviewer is exhausted)
- **THEN** the scheduler refuses to admit or start the change, preventing speculative starts, and keeps the change in `READY` status.

#### Scenario: New READY change admission blocked in WAIT mode
- **WHEN** a change is evaluated for execution while the scheduler is in `WAIT` mode
- **THEN** the scheduler blocks admission and returns a structured unmet reason indicating capacity wait state.

#### Scenario: READY change admitted only when complete primary pair is available
- **WHEN** a change is in `READY` status, the scheduler is in `RUN` mode, and both implementer and reviewer providers are verified available
- **THEN** the scheduler admits the change and queues the execution job.

### Requirement: In-flight job preservation and WAITING_CAPACITY
The system SHALL preserve in-flight jobs and checkpoints, transitioning jobs to `WAITING_CAPACITY` whenever a required primary provider is unavailable.

#### Scenario: In-flight job pauses in WAITING_CAPACITY without data loss
- **WHEN** an active job requires an implementer or reviewer whose primary provider is exhausted
- **THEN** the system transitions the job to `WAITING_CAPACITY`, records the blocking provider and reason, and preserves all completed check, diff, review, and audit evidence intact.

#### Scenario: Complementary pairing invariant strictly preserved during capacity shortage
- **WHEN** an in-flight job requires complementary review and the configured reviewer provider is exhausted
- **THEN** the system SHALL NOT perform self-review, SHALL NOT substitute an unauthorized provider, and SHALL transition the job to `WAITING_CAPACITY`.
