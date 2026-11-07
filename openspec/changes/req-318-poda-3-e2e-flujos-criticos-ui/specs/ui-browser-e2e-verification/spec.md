## Purpose

Verificar de forma auténtica, determinista y automatizada en navegador real (Playwright Chromium headless) los recorridos críticos de la interfaz de usuario de mini me, validando la interacción DOM, la comunicación con FastAPI, la persistencia durable en PostgreSQL efímero y la integración en el gate de CI.

## ADDED Requirements

### Requirement: Browser-driven E2E execution over served application
The testing system SHALL execute end-to-end tests inside a real browser instance operating against the served Angular production build and the running FastAPI backend with an ephemeral migrated PostgreSQL database.

#### Scenario: Real browser operates against full stack
- **WHEN** the E2E test suite executes
- **THEN** a headless Chromium browser navigates the served application URL
- **AND** all user interactions (clicks, inputs, navigation) are performed through browser DOM events
- **AND** HTTP API requests and responses are routed through the live FastAPI instance
- **AND** mocked browser assertions without real page execution SHALL NOT qualify as E2E evidence.

### Requirement: Project pause and resume lifecycle verification
The E2E test suite SHALL verify the complete project pause and resume user journey from the Proyectos view.

#### Scenario: Operator toggles project pause and confirms persistence
- **WHEN** the operator triggers the project pause action in the Proyectos interface
- **THEN** the browser sends the pause request to `/api/v1/projects/{project_id}/pause`
- **AND** the project state in PostgreSQL transitions to paused
- **AND** the UI reactively updates the project badge to indicate the paused state
- **AND** reloading the page (`F5`) in the browser retains and displays the paused state from the database.

### Requirement: Provider model administration toggle verification
The E2E test suite SHALL verify the model administration toggle journey from the `/administracion/modelos-proveedores` route.

#### Scenario: Operator toggles model enabled state
- **WHEN** the operator navigates to `/administracion/modelos-proveedores` and toggles a model switch
- **THEN** the browser issues a PATCH request to `/api/v1/admin/providers/models/{id}/enabled`
- **AND** the enabled flag is updated in the PostgreSQL database
- **AND** the UI reflects the updated switch state without full page refresh.

### Requirement: Observable error feedback and runtime resilience
The E2E test suite SHALL verify that application and network errors produce visible, accessible feedback without crashing the Angular runtime.

#### Scenario: Server error displays user-facing message without white screen
- **WHEN** an action triggers an API error or network failure
- **THEN** the application SHALL render an observable error notification or badge in the DOM
- **AND** the Angular app shell SHALL remain responsive without blank screen crashes.

### Requirement: E2E pipeline gate integration and candidate SHA binding
The PR validation pipeline SHALL execute the E2E test suite as a required job bound to the candidate commit SHA.

#### Scenario: E2E tests pass and report candidate SHA
- **WHEN** the E2E validation job executes in CI
- **THEN** all critical journeys pass with exit code 0 in ~15-30 seconds
- **AND** the tested commit SHA is reported in the step logs.

#### Scenario: E2E failure blocks pull request gate
- **WHEN** any E2E journey fails
- **THEN** the E2E validation job SHALL fail with exit code 1
- **AND** the `pr-gate` job SHALL fail closed, blocking merge.

### Requirement: Strict isolation from production and paid services
The E2E test suite SHALL execute strictly against ephemeral local services without accessing production data or invoking paid external APIs.

#### Scenario: Isolation boundary enforcement
- **WHEN** E2E tests run
- **THEN** zero production credentials or secrets are available in the test runner
- **AND** zero external paid LLM or provider endpoints are called.
