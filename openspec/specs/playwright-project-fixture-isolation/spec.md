# Playwright Project Fixture Isolation Specification

## Purpose
Provides deterministic, isolated project-state setup for Playwright E2E tests that exercise project lifecycle behavior.

## Requirements

### Requirement: Project lifecycle E2E fixture resets only disposable test state
The Playwright project-state reset SHALL remove or terminally classify residual active runs belonging to the designated E2E project in the configured disposable test database before it resets that project's active state. It SHALL NOT mutate a production database, another project, or a run outside the E2E fixture.

#### Scenario: Residual E2E runs do not defer project pause
- **GIVEN** the designated E2E project has residual active runs in the configured test database
- **WHEN** the project lifecycle fixture resets state and the pause/resume E2E runs
- **THEN** only residual runs belonging to that E2E project SHALL be cancelled or marked inactive in the test database
- **AND** project pause SHALL transition immediately to `PAUSED`
- **AND** the UI SHALL reflect pause and resume without a reload.

#### Scenario: Reset refuses a non-test database target
- **GIVEN** the configured database cannot be positively identified as the disposable E2E database
- **WHEN** the fixture attempts to reset project or run state
- **THEN** it SHALL stop with a visible non-zero test failure before any mutation.

#### Scenario: Reset failure is visible to the E2E result
- **GIVEN** the fixture cannot complete its authorized reset operation
- **WHEN** setup or teardown runs
- **THEN** the affected E2E test SHALL fail with the cleanup cause
- **AND** the fixture SHALL NOT convert the failure into a warning-only pass.

#### Scenario: Unrelated project state is preserved
- **GIVEN** the test database contains runs for projects other than the designated E2E project
- **WHEN** the project lifecycle fixture resets the E2E project
- **THEN** unrelated project runs and state SHALL remain unchanged.
