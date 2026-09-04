# Specification: Add runtime diagnostic latency header to API health check

## Requirements

### REQ-ADD-RUNTIME-DIAGNOSTIC-LATENCY-HEADER-TO-API-HEALTH-CHECK-1: Primary Capability
Include X-Runtime-Diagnostic header on API health check response to measure round-trip gateway latency.

#### Scenario 1: GET /api/health includes X-Runtime-Diagnostic header in response
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** GET /api/health includes X-Runtime-Diagnostic header in response.

#### Scenario 2: Header contains timestamp in ISO format
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** Header contains timestamp in ISO format.

#### Scenario 3: All deterministic checks pass
- **GIVEN** the configured environment for `mini me`,
- **WHEN** the capability is invoked,
- **THEN** All deterministic checks pass.
