## MODIFIED Requirements

### Requirement: Mandatory Real Unit and E2E Test Execution
During Apply/Verify, the system SHALL execute real automated tests selected for the candidate change, based on files changed by that change and tests added or modified for it, within the project's test conventions. The selected tests SHALL execute with exit code 0 before the change advances, and the system SHALL preserve coordinator-observed evidence containing the exact command, exit code, and captured output. The system SHALL reject skipped, mocked-out/vacuous, failed, or empty test execution as a passing result. The coordinator SHALL NOT run the complete project test suite as its Apply/Verify gate; the project's full-suite CI/CD remains outside mini me and runs before merge.

#### Scenario: Implementation includes passing unit and E2E tests with real test runner execution
- **GIVEN** the implementer completes source changes and writes corresponding unit, integration, or E2E tests
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** it executes the changed tests and relevant tests mapped to the changed source files, without invoking the complete project suite
- **AND** it preserves the exact test command, exit code, and captured output as observable evidence
- **AND** it advances only when the selected tests execute and pass with exit code 0

#### Scenario: Unrelated pre-existing test failure is outside the focused gate
- **GIVEN** the candidate change modifies one code area and an unrelated, pre-existing test fails outside the selected set
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** the unrelated test is not run by that gate
- **AND** the focused gate's result is determined by the selected tests and their captured execution evidence

#### Scenario: No relevant tests cannot produce a passing result
- **GIVEN** changed executable code has no tests selected by the documented mapping and no changed tests are present
- **WHEN** the Apply/Verify automated test gate attempts to execute its selection
- **THEN** it records that no tests were selected or collected
- **AND** it does not treat the empty selection as a passing test result or fall back to the complete suite

#### Scenario: Failing tests trigger immediate self-correction loop
- **GIVEN** the Apply/Verify automated test gate runs the selected tests
- **WHEN** a selected test fails or returns a non-zero exit code
- **THEN** the existing Apply self-correction flow receives the observed failure evidence
- **AND** the change does not advance until a subsequent focused execution passes

## ADDED Requirements

### Requirement: Single-Pass Test Import Mapping
For each focused test-selection operation, the system SHALL parse each candidate pytest file's imports at most once and SHALL build an inverse module-to-tests index for direct imports. It SHALL use that index to find tests for changed source modules and SHALL NOT re-parse every test file for each changed module. Existing test path and module-name matching behavior SHALL remain unchanged.

#### Scenario: Import mapping indexes each test file once
- **GIVEN** a candidate has multiple changed source modules and multiple candidate pytest files
- **WHEN** the test selector builds direct-import relationships
- **THEN** it parses each candidate pytest file's AST once and records its imported modules in an inverse module-to-tests index
- **AND** it looks up each changed source module in that index without re-parsing test files
- **AND** it retains the existing test path, module-name, and direct-import selection results
