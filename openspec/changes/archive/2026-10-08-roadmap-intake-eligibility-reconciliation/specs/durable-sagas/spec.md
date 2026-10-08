## ADDED Requirements

### Requirement: Claimed reconciliation cancellation
The system SHALL acquire a fresh recovery claim before cancelling a reconciled intake saga and SHALL preserve saga/action/audit history. Expired historical claims SHALL be observational evidence only.

#### Scenario: Expired claim is not reused
- **WHEN** a prior intake claim has expired
- **THEN** reconciliation acquires a new authoritative claim before mutation
