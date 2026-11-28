# Spec Delta

## Purpose

Reprojects durable historical telemetry observations with the current autonomy semantics so Dashboard history becomes immediately consistent without deleting or rewriting authoritative run history.

## ADDED Requirements

### Requirement: Non-destructive historical telemetry reprojection
The system SHALL recalculate temporal telemetry for every eligible historical run available in PostgreSQL, across all registered projects represented by those runs, using the current autonomy and outcome rules. Reprojection SHALL be idempotent, SHALL preserve runs, stage events, operator actions, gates, settlements, and audit evidence, SHALL require no destructive migration, and SHALL return explicit no-data or unverified states when historical evidence is insufficient.

#### Scenario: All stored project histories are reprojection inputs
- **GIVEN** PostgreSQL contains completed historical runs for picas-fijas, mini-me, multiplo, and boxio
- **WHEN** the Dashboard requests the temporal telemetry projection
- **THEN** the projection evaluates eligible runs from all four projects using the current proportional autonomy rules
- **AND** each project series and the Global series reflect the recalculated historical observations

#### Scenario: Reprojection is immediately visible without destructive mutation
- **GIVEN** a stored run previously rendered as 0 percent because it had one governance gate and later autonomous stages
- **WHEN** the autonomy projection is requested after the rule update
- **THEN** the response immediately reports the proportional value and governance outcome
- **AND** the underlying run and evidence records remain unchanged
- **AND** no destructive migration or historical deletion is required

#### Scenario: Repeated reprojection is idempotent
- **GIVEN** the same historical run set is projected more than once
- **WHEN** the same dimension and window are requested repeatedly
- **THEN** the returned observations, outcomes, source references, and no-data states are stable
- **AND** the read path emits no duplicate records, events, or durable mutations

#### Scenario: Ambiguous historical evidence fails closed
- **GIVEN** a historical run has contradictory gate, action, or stage evidence
- **WHEN** it is included in reprojection
- **THEN** it is excluded from the autonomy numerator and denominator
- **AND** the projection reports it as unverified without guessing a proportional value
