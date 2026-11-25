## ADDED Requirements

### Requirement: Watchdog context in Trabajo Actual
The existing `Diagnóstico & Supervisión` card SHALL show only server-confirmed activity timing and pulse state for the selected active run, a chronological timeline of that run's persisted Watchdog interventions, and a link to `/mejora-continua`. An authorized operator MAY request an immediate diagnosis through the existing Watchdog authority; the UI SHALL show accepted/running/completed/error states from API responses and SHALL NOT claim that a diagnosis or recovery succeeded before its result is persisted.

#### Scenario: Show current run supervision
- **WHEN** Trabajo Actual displays an active run with persisted activity and Watchdog records
- **THEN** the card presents the current stage's elapsed time, latest observed activity, and interventions for that run
- **AND** links to the improvement feed
- **AND** does not mix records from another project, run, stage, or candidate

#### Scenario: Request immediate diagnosis
- **WHEN** an authorized operator requests diagnosis for the selected active run
- **THEN** the API routes the request through existing claim and recovery authorities
- **AND** the card reflects the returned accepted or final state without bypassing a human gate

#### Scenario: No active run or no Watchdog evidence
- **WHEN** there is no active run or no persisted Watchdog record for it
- **THEN** the card shows the existing no-active-run or no-intervention state
- **AND** it does not fabricate a health score, pulse, diagnosis, or timeline entry
