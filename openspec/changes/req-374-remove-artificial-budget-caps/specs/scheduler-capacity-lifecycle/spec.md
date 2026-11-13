## MODIFIED Requirements

### Requirement: Primary-driven scheduler mode state machine
The system SHALL operate the scheduler under three explicit modes: `RUN`, `DRAIN`, and `WAIT`, driven by configured primary provider capacity. Configured OpenRouter fallback SHALL be available only for eligible in-flight work and only for a stage whose assigned primary provider has verified quota/rate-limit exhaustion. Fallback SHALL NOT depend on an internal budget-policy row, daily/monthly cap, or headroom. Availability of a different role's provider SHALL NOT block fallback for the currently blocked stage.

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
- **WHEN** an active Run is in `IMPLEMENTING`, the configured execution provider has recent quota/rate-limit exhaustion, the reviewer provider remains available, and a compatible fallback profile is configured
- **THEN** the scheduler invokes that exact fallback profile for Apply without a local budget-policy/headroom prerequisite and preserves the reviewer role for any required independent review.

#### Scenario: Available execution primary does not use fallback
- **WHEN** an active Run is in `IMPLEMENTING` and its configured execution provider has fresh successful capacity evidence
- **THEN** the scheduler uses that execution provider and does not invoke fallback, regardless of the review provider's capacity state.

#### Scenario: Transition to WAIT when no primary work can progress
- **WHEN** the scheduler is in `DRAIN` mode and no active in-flight job can make safe progress due to primary provider unavailability (and fallback is unconfigured, unavailable, or lacking a distinct model)
- **THEN** the scheduler transitions to `WAIT`, pauses pipeline polling, and logs a `SCHEDULER_MODE_CHANGED` event.

#### Scenario: Deterministic return to RUN upon verified pair recovery
- **WHEN** the scheduler is in `WAIT` or `DRAIN` mode and positive probe evidence confirms that all required roles in the primary pair are verified available
- **THEN** the scheduler transitions to `RUN` and resumes normal work admission.

#### Scenario: DeepSeek audit availability does not drive primary scheduler mode
- **WHEN** DeepSeek Direct experiences a transient error or rate limit
- **THEN** the system handles the audit failure within the 004 audit lifecycle and SHALL NOT cause a scheduler transition to `DRAIN` or `WAIT`.

### Requirement: In-flight job preservation and WAITING_CAPACITY
The system SHALL preserve in-flight jobs and checkpoints, transitioning jobs to `WAITING_CAPACITY` whenever a required primary provider is unavailable and no eligible configured fallback can proceed. The scheduler SHALL NOT use artificial budget caps or headroom as fallback eligibility conditions.

#### Scenario: In-flight job pauses in WAITING_CAPACITY without data loss
- **WHEN** an active job requires an implementer or reviewer whose primary provider is exhausted and OpenRouter fallback is unconfigured, unavailable, or ineligible
- **THEN** the system transitions the job to `WAITING_CAPACITY`, records the blocking provider and reason, and preserves all completed check, diff, review, and audit evidence intact.

#### Scenario: Complementary pairing invariant strictly preserved during capacity shortage
- **WHEN** an in-flight job requires complementary review, the configured primary reviewer provider is exhausted, and no distinct allowed reviewer model is available
- **THEN** the system SHALL NOT perform self-review, SHALL NOT substitute an unauthorized provider, and SHALL transition the job to `WAITING_CAPACITY`.
