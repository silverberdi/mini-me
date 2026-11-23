# Spec Delta

## ADDED Requirements

### Requirement: Dashboard renders temporal telemetry without weakening existing authorities

The Dashboard SHALL include the temporal multi-series telemetry projection and interactive controls defined by `temporal-multiseries-telemetry` while retaining the existing dashboard overview, verified liquidated-cost authority, secret sanitization, responsive delivery, and compact active-Run summary. The Dashboard SHALL NOT derive cost from tokens, create a second cost authority, or turn absent telemetry into normal-looking zero values.

#### Scenario: Existing dashboard and temporal telemetry coexist

- **WHEN** the operator loads the Dashboard with registered projects, an active Run, and historical telemetry
- **THEN** the Dashboard renders the temporal telemetry controls and series
- **AND** retains the compact active-Run summary and its direct Trabajo Actual link
- **AND** the telemetry projection uses the existing authenticated Dashboard read path and sanitized payloads

#### Scenario: Missing verified cost remains no-data

- **WHEN** the selected cost window has token usage but no verifiable liquidated ledger settlement
- **THEN** the temporal cost dimension renders an explicit no-data state
- **AND** it does not display a token-derived USD value, zero-as-substitute, or provider attribution
