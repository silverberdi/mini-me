# intake-abandoned-reconciliation Specification

## Purpose
TBD - created by archiving change roadmap-intake-eligibility-reconciliation. Update Purpose after archive.

## Requirements

### Requirement: Evidence-bound abandoned intake reconciliation
The system SHALL reconcile only an active or blocked INTAKE saga by a fresh claim and exact persisted saga/action/binding identity. It SHALL support only INVALID_DISCOVERY and DEFERRED_ROADMAP dispositions and SHALL be idempotent.

#### Scenario: Invalid discovery is cancelled
- **WHEN** an exact saga-owned accidental intake is reconciled as INVALID_DISCOVERY
- **THEN** PREPARING backlog and DISCOVERED change transition canonically to CANCELLED and the saga is cancelled

#### Scenario: Deferred roadmap preserves planning identity
- **WHEN** an exact saga-owned future roadmap intake is reconciled as DEFERRED_ROADMAP
- **THEN** PREPARING backlog and DISCOVERED change transition canonically to BLOCKED with `ROADMAP_NOT_PREPARATION_ELIGIBLE`, and the saga is cancelled

### Requirement: Guarded side-effect cleanup
The system SHALL close only a saga-proven issue through an idempotent ISSUE_CLOSE action. It SHALL remove only a saga-owned, binding-derived untracked generated directory after workspace-guard authorization and Git/path/content checks. It SHALL refuse tracked, escaped, symlinked, or ambiguous content.

#### Scenario: Tracked artifact prevents cleanup
- **WHEN** any candidate artifact path is tracked or otherwise ambiguous
- **THEN** reconciliation fails closed without removing the directory
