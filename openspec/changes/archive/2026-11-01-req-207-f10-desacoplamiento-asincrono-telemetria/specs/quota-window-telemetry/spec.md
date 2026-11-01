# Spec Delta

## Purpose

Expone observaciones de capacidad de proveedores basadas en fuentes reales, con ventanas rodantes de cinco horas, reinicios y balances verificables, sin convertir valores ausentes o simulados en autorización operativa.

## ADDED Requirements

### Requirement: Provider strategy observations
The system SHALL obtain quota or balance observations through a provider-specific strategy for Antigravity, Codex, and DeepSeek, preserving the provider source, account identity when available, observation time, and parsing outcome.

#### Scenario: Antigravity five-hour usage
- **WHEN** telemetry queries an authenticated Antigravity CLI exposing `/usage`
- **THEN** the observation contains the real remaining percentage or amount, five-hour window identity, and reset timestamp when reported by the CLI

#### Scenario: Codex capacity window
- **WHEN** telemetry queries the authenticated Codex capacity source
- **THEN** the observation contains the provider-reported remaining capacity and reset timestamp for each available window, or an explicit unknown result when the source is incomplete

#### Scenario: DeepSeek live balance
- **WHEN** telemetry queries DeepSeek
- **THEN** it reads the live account balance endpoint and exposes the returned monetary balance and availability without substituting a static quota number

### Requirement: Bounded telemetry cache
The system SHALL cache an otherwise equivalent provider observation for no more than 60 seconds and SHALL expose freshness and source metadata with every response.

#### Scenario: Fresh cache hit
- **WHEN** the same provider and account are queried within 60 seconds
- **THEN** the service returns the cached observation with its original timestamp and does not invoke the external source again

#### Scenario: Expired cache refresh
- **WHEN** the cached observation is 60 seconds old or older
- **THEN** the service obtains a new observation and replaces the expired cache entry, or reports the source failure explicitly

### Requirement: No inferred quota authority
The system SHALL distinguish unavailable, malformed, stale, and verified observations and SHALL NOT present hardcoded, simulated, or inferred percentages, reset times, or balances as real capacity.

#### Scenario: Malformed provider output
- **WHEN** a provider returns output that cannot be parsed unambiguously
- **THEN** telemetry reports an unknown/malformed observation and does not mark the provider available or exhausted based on inference

