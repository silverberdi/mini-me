## ADDED Requirements

### Requirement: CLI responses use the canonical active-gate action path
The `minime request run <project_id> --response <text>` command SHALL submit the supplied response for the single current human gate of that project's active Run through the same canonical authority, validation, durable audit, and idempotency behavior used by the web operator flow. A response SHALL be bound to the current Run and gate identity; it SHALL NOT implicitly authorize an action that the active gate does not permit. If there is no active Run with a current human gate, or the target identity is ambiguous or stale, the command SHALL fail clearly without mutating the Run or dispatching work.

#### Scenario: CLI response resolves the current gate through the canonical path
- **GIVEN** one active Run for the project is waiting at a current human gate
- **WHEN** the operator invokes `minime request run <project_id> --response <text>`
- **THEN** the response is checked against the current gate and processed through the canonical operator-action path
- **AND** the accepted response and outcome are durably audited with sensitive text redacted as required
- **AND** only the transition authorized by that gate may resume
- **AND** the same Run continues from that gate without replaying stages already completed.

#### Scenario: Repeating the same response does not duplicate its effect
- **GIVEN** a CLI response has already been durably accepted for a particular Run and gate
- **WHEN** the same response is submitted again for that gate
- **THEN** the command returns or reports the prior action result
- **AND** it creates no duplicate transition, job, agent dispatch, or external side effect.

#### Scenario: Missing, stale, or ambiguous gate response is rejected safely
- **GIVEN** the project has no current human gate, the gate has changed, or the active Run identity is ambiguous
- **WHEN** the operator submits a CLI response
- **THEN** the command reports the applicable no-gate, stale-state, or ambiguity error
- **AND** it does not mutate Run state, record an accepted response for a different gate, or start work.
