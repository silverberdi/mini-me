# Scheduler Capacity Lifecycle Specification

## Purpose

Manages scheduler capacity lifecycle modes (`RUN`, `DRAIN`, `WAIT`) and enforces strict primary-pair admission control and in-flight job preservation.

## Requirements

### Requirement: Primary-driven scheduler mode state machine
The system SHALL operate the scheduler under three explicit modes: `RUN`, `DRAIN`, and `WAIT`, driven strictly by the availability of configured primary execution providers (Codex and Antigravity) with budgeted OpenRouter fallback available exclusively in `DRAIN` during dual-primary exhaustion.

#### Scenario: Normal RUN mode operation
- **WHEN** all required primary provider roles for the project's configured pair (implementer AND reviewer) are verified available
- **THEN** the scheduler operates in `RUN` mode, admitting new `READY` changes and executing active pipelines using primary subscription providers without OpenRouter fallback.

#### Scenario: Transition to DRAIN when any required primary role is unavailable
- **WHEN** any required primary role in the configured pair is exhausted or unavailable (e.g. Codex is available but Antigravity is exhausted, or the reverse)
- **THEN** the scheduler transitions from `RUN` to `DRAIN`, logs a `SCHEDULER_MODE_CHANGED` event, and halts admission of new `READY` changes.

#### Scenario: In-flight execution during DRAIN mode
- **WHEN** the scheduler is in `DRAIN` mode and an in-flight job reaches a phase whose specific primary provider is currently available (e.g. Codex implementation while Antigravity is exhausted)
- **THEN** the scheduler allows that specific phase to execute with the primary provider and advance until it reaches an unavailable provider phase without invoking OpenRouter.

#### Scenario: In-flight execution during DRAIN mode with OpenRouter fallback
- **WHEN** the scheduler is in `DRAIN` mode, both primary providers (Codex and Antigravity) are exhausted, an in-flight job is blocked on an execution stage, and OpenRouter fallback is enabled, budgeted, and independently modeled
- **THEN** the scheduler executes that phase using OpenRouter fallback and advances the candidate.

#### Scenario: Transition to WAIT when no primary work can progress
- **WHEN** the scheduler is in `DRAIN` mode and no active in-flight job can make safe progress due to primary provider unavailability (and fallback is unconfigured, exhausted, over budget, breached, or lacking a distinct model)
- **THEN** the scheduler transitions to `WAIT`, pauses pipeline polling, and logs a `SCHEDULER_MODE_CHANGED` event.

#### Scenario: Deterministic return to RUN upon verified pair recovery
- **WHEN** the scheduler is in `WAIT` or `DRAIN` mode and positive probe evidence confirms that all required roles in the primary pair are verified available
- **THEN** the scheduler transitions to `RUN` and resumes normal work admission.

#### Scenario: DeepSeek audit availability does not drive primary scheduler mode
- **WHEN** DeepSeek Direct experiences a transient error or rate limit
- **THEN** the system handles the audit failure within the 004 audit lifecycle and SHALL NOT cause a scheduler transition to `DRAIN` or `WAIT`.

### Requirement: Strict admission control for READY work
The system SHALL admit a new `READY` change ONLY when all required primary roles for the configured pair have verified availability in `RUN` mode, and SHALL strictly prohibit admission during `DRAIN` or `WAIT` modes regardless of OpenRouter fallback availability.

#### Scenario: New READY change admission blocked in DRAIN mode
- **WHEN** a change reaches `READY` status while the scheduler is in `DRAIN` mode (even if OpenRouter fallback is enabled and budgeted)
- **THEN** the scheduler refuses to admit or start the change, preventing speculative starts, and keeps the change in `READY` status.

#### Scenario: New READY change admission blocked in WAIT mode
- **WHEN** a change is evaluated for execution while the scheduler is in `WAIT` mode
- **THEN** the scheduler blocks admission and returns a structured unmet reason indicating capacity wait state.

#### Scenario: READY change admitted only when complete primary pair is available
- **WHEN** a change is in `READY` status, the scheduler is in `RUN` mode, and both implementer and reviewer providers are verified available
- **THEN** the scheduler admits the change and queues the execution job.

#### Scenario: OpenRouter capacity never satisfies READY change admission
- **WHEN** evaluating admission criteria for a `READY` change
- **THEN** OpenRouter fallback capacity SHALL NOT be counted as provider availability or satisfy primary pair readiness.

### Requirement: In-flight job preservation and WAITING_CAPACITY
The system SHALL preserve in-flight jobs and checkpoints, transitioning jobs to `WAITING_CAPACITY` whenever a required primary provider is unavailable and no eligible budgeted fallback can proceed.

#### Scenario: In-flight job pauses in WAITING_CAPACITY without data loss
- **WHEN** an active job requires an implementer or reviewer whose primary provider is exhausted and OpenRouter fallback is unavailable, exhausted, or over budget
- **THEN** the system transitions the job to `WAITING_CAPACITY`, records the blocking provider and reason, and preserves all completed check, diff, review, and audit evidence intact.

#### Scenario: Complementary pairing invariant strictly preserved during capacity shortage
- **WHEN** an in-flight job requires complementary review, the configured primary reviewer provider is exhausted, and no distinct allowed OpenRouter reviewer model is available
- **THEN** the system SHALL NOT perform self-review, SHALL NOT substitute an unauthorized provider, and SHALL transition the job to `WAITING_CAPACITY`.
