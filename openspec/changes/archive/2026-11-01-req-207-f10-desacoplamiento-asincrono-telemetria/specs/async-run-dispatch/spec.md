# Spec Delta

## Purpose

Permite aceptar operaciones largas del orquestador sin mantener conexiones HTTP abiertas, preservando identidad, autorización, aislamiento transaccional, idempotencia y evidencia durable del Run.

## ADDED Requirements

### Requirement: Immediate asynchronous run acceptance
The system SHALL validate an authorized Run or gate request synchronously and return HTTP 202 Accepted with a durable Run or operation identity before starting long-running provider work.

#### Scenario: Run is accepted without proxy timeout
- **WHEN** an authorized operator posts a valid request to `/api/v1/projects/{project_id}/requests/run`
- **THEN** the API returns HTTP 202 with the Run identity and an observable accepted status without waiting for model inference

#### Scenario: Invalid request is rejected synchronously
- **WHEN** the request is malformed, unauthorized, or conflicts with an active Run
- **THEN** the API returns the existing appropriate client error and SHALL NOT enqueue duplicate provider work

### Requirement: Isolated background execution
The system SHALL execute accepted orchestration work outside the request transaction using a fresh, bounded database session and canonical lifecycle transition authority.

#### Scenario: Worker commits stage effects independently
- **WHEN** a worker executes an accepted Run and persists a stage transition
- **THEN** the transition and evidence are committed in the worker unit of work and the request session is already closed

#### Scenario: External failure is observable
- **WHEN** background provider execution fails, times out, or is cancelled
- **THEN** the Run records a truthful classified outcome and the API read model exposes it without reporting a false HTTP disconnect

### Requirement: Idempotent accepted operations
The system SHALL bind an accepted operation to the project, Request, Run and caller intent so retries do not create duplicate active executions.

#### Scenario: Repeated dispatch is deduplicated
- **WHEN** the same authorized dispatch is submitted again while its accepted Run is active
- **THEN** the API returns the existing operation identity and SHALL NOT create a second active Run


### Requirement: Real-time event streaming for accepted run transitions and gates
The system SHALL expose a Server-Sent Events (SSE) stream endpoint `GET /api/v1/events` providing immediate push notifications of stage transitions, human gate requests, and provider quota changes to connected clients.

#### Scenario: Human gate event is pushed instantly to client
- **WHEN** an accepted background Run transitions to `HUMAN_REQUIRED`
- **THEN** the SSE broker broadcasts a `human_required` event payload to all connected operator streams within milliseconds, eliminating polling latency

#### Scenario: Client handles reconnects transparently
- **WHEN** an SSE connection drops or is interrupted
- **THEN** the client automatically reconnects and re-synchronizes the latest active run state without loss of consistency
