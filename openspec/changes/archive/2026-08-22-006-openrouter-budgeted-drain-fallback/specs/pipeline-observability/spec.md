## ADDED Requirements

### Requirement: Budget and fallback observability via API
The system SHALL provide REST API endpoints to query token usage, committed spend, active reservations, daily/monthly budget caps, remaining headroom, unresolved settlements, policy breach status, and OpenRouter fallback configuration status with full secret redaction.

#### Scenario: Query budget usage and spend status via API
- **WHEN** a client sends `GET /budget/usage` or `GET /projects/{project_id}/budget`
- **THEN** the API returns structured JSON with daily and monthly spend caps (UTC), committed spend, currently reserved spend, remaining reservable headroom, unresolved settlements count and amounts, policy breach flag (`is_breached`), and token usage breakdown by canonical model.

#### Scenario: Query OpenRouter fallback status via API
- **WHEN** a client sends `GET /providers/openrouter/status`
- **THEN** the API returns structured JSON indicating whether OpenRouter fallback is enabled, allowed canonical models for implementer and reviewer roles, active budget status, policy breach status, recent fallback invocation counts, and fallback denial reasons if any.

#### Scenario: Secret redaction in observability endpoints
- **WHEN** any budget or provider status endpoint is queried
- **THEN** all provider API keys, tokens, and authorization headers are completely redacted.

### Requirement: Budget and fallback observability via CLI
The system SHALL provide CLI commands to inspect budget consumption against caps, active reservations, token usage breakdowns, policy breach status, and OpenRouter fallback readiness.

#### Scenario: Inspect budget usage via CLI
- **WHEN** an operator runs `minime budget status`
- **THEN** the CLI displays a formatted summary of daily and monthly spend against configured caps (UTC), committed spend, active reservations, remaining headroom, unresolved settlements, and policy breach warnings if present.

#### Scenario: Inspect OpenRouter fallback status via CLI
- **WHEN** an operator runs `minime providers openrouter`
- **THEN** the CLI displays fallback enablement, configured allowed canonical models, pricing snapshot rates, policy health (`is_breached`), and recent fallback execution metrics.
