## ADDED Requirements

### Requirement: Capacity and scheduler observability via API
The system SHALL expose REST API endpoints to inspect scheduler mode (`RUN`, `DRAIN`, `WAIT`), primary provider health states, capacity reset windows, `WAITING_CAPACITY` blockage reasons, and crash recovery status with secret redaction.

#### Scenario: Query scheduler status via API
- **WHEN** a client sends `GET /scheduler/status`
- **THEN** the API returns structured JSON containing current scheduler mode, active in-flight job counts, admission status, primary capacity availability, and reason if in `DRAIN` or `WAIT`.

#### Scenario: Query provider health and capacity windows via API
- **WHEN** a client sends `GET /providers/health`
- **THEN** the API returns structured JSON with each primary provider's status (`available`, `temporarily_unavailable`, `exhausted`, `degraded`), consecutive failure counts, last result class, and known capacity reset timestamps.

#### Scenario: Query job blockage details via API
- **WHEN** a client sends `GET /jobs/{job_id}` for a job in `WAITING_CAPACITY` or `RECOVERY_BLOCKED`
- **THEN** the response includes structured fields indicating the blocking provider identity, last outcome class, expected reset timestamp if available, or lock recovery blockage path and reason.

### Requirement: Capacity and scheduler observability via CLI
The system SHALL provide CLI commands to inspect scheduler mode, primary provider capacity health, and in-flight capacity blockage.

#### Scenario: Inspect scheduler status via CLI
- **WHEN** an operator runs `minime scheduler status`
- **THEN** the CLI displays current scheduler mode (`RUN`, `DRAIN`, `WAIT`), admission policy status, active in-flight jobs, and primary capacity state.

#### Scenario: Inspect provider health via CLI
- **WHEN** an operator runs `minime providers health`
- **THEN** the CLI displays a formatted table of configured primary providers, their health status, failure counts, last outcome, and reset timestamps.
