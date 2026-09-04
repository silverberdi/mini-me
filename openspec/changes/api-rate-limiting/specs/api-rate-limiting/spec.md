# Specification: API Rate Limiting

## Requirements

### REQ-API-RATE-LIMITING-1: Primary Capability
Rate limiting implementation.

#### Scenario 1: 429 returned on limit
- **GIVEN** the configured environment for `API Project`,
- **WHEN** the capability is invoked,
- **THEN** 429 returned on limit.
