## MODIFIED Requirements

### Requirement: Mandatory Real Unit and E2E Test Execution
During Apply/Verify, the system SHALL execute real automated tests selected for the candidate change, based on files changed by that change and tests added or modified for it, within the candidate project's actual technological test conventions. If the project configuration defines deterministic verification commands in `project.checks`, the system SHALL prioritize executing those commands. In the absence of explicit project checks, the system SHALL dynamically detect the project's native test harness (such as root or subproject `package.json` with `npm test`, `Cargo.toml` with `cargo test`, `go.mod` with `go test`, or Python test configurations with `pytest`). The selected tests SHALL execute with exit code 0 before the change advances, and the system SHALL preserve coordinator-observed evidence containing the exact command, exit code, duration, and captured output. The system SHALL reject skipped, mocked-out/vacuous, failed, or empty test execution as a passing result. When test selection or discovery cannot identify a supported test suite, the diagnostic failure SHALL accurately report the technology inspectable in the candidate worktree and SHALL NOT falsely report that Python or `pytest` was expected or omitted.

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

#### Scenario: Root-level Node project executes native npm test suite
- **GIVEN** a candidate worktree with a root `package.json` declaring test scripts (such as a web application or Node service)
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** it detects the root Node project manifest
- **AND** it executes `npm test` inside the candidate worktree root
- **AND** it records the observable command output, exit code, and execution evidence without demanding Python pytest files.

#### Scenario: Subfolder frontend project executes subfolder npm test suite
- **GIVEN** a monorepo candidate worktree with changes restricted to `frontend/` and a `frontend/package.json` manifest
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** it executes `npm --prefix frontend test` inside the candidate worktree
- **AND** it records the test execution evidence.

#### Scenario: Explicit project checks override default detection
- **GIVEN** a project configuration that declares explicit verification commands in `project.checks`
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** it executes the configured project check commands inside the candidate worktree
- **AND** it advances only when all configured checks pass with exit code 0.

#### Scenario: Honest diagnostic on unsupported or missing test suite
- **GIVEN** a candidate change in a project lacking recognizable test manifests or configured checks
- **WHEN** the Apply/Verify automated test gate attempts execution
- **THEN** it halts fail-closed
- **AND** its failure diagnostic accurately describes the missing test declaration without attributing the failure to pytest unless Python test artifacts are genuinely present.

#### Scenario: Failing tests trigger immediate self-correction loop
- **GIVEN** the Apply/Verify automated test gate runs the selected tests
- **WHEN** a selected test fails or returns a non-zero exit code
- **THEN** the existing Apply self-correction flow receives the observed failure evidence
- **AND** the change does not advance until a subsequent focused execution passes
