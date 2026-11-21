## ADDED Requirements

### Requirement: CLI acknowledgement uses the existing gate-response path
The `minime request ack <project_id>` command SHALL forward an explicit `operator_response=None` together with `operator_ack=True` through the existing request command path. It SHALL retain the same active-gate checks, authorization, idempotency, and durable operator-action recording as the existing CLI and web acknowledgement paths; it SHALL NOT create a separate acknowledgement implementation.

#### Scenario: CLI acknowledgement reaches shared request validation
- **GIVEN** a high-complexity implementation PR is waiting for the informational «Estoy enterado» acknowledgement
- **WHEN** the operator runs `minime request ack <project_id>`
- **THEN** the command invokes the shared request path with `operator_ack=True` and `operator_response=None`
- **AND** the shared path validates and records the acknowledgement without passing a Typer option declaration as response data.

#### Scenario: CLI acknowledgement without an eligible gate follows existing behavior
- **GIVEN** there is no active gate that accepts an informational acknowledgement
- **WHEN** the operator runs `minime request ack <project_id>`
- **THEN** the existing gate validation rejects or reports the action according to its current behavior
- **AND** no separate CLI-only authorization or state transition occurs.
