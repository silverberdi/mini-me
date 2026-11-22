## MODIFIED Requirements

### Requirement: Mandatory Real Unit and E2E Test Execution
During Apply/Verify, the system SHALL execute real automated tests selected for the candidate change, based on files changed by that change and tests added or modified for it, within the candidate project's actual technological test conventions. If the project configuration defines deterministic verification commands in `project.checks`, the system SHALL prioritize executing those commands. In the absence of explicit project checks, the system SHALL dynamically detect the project's native test harness (such as root or subproject `package.json` with `npm test`, `Cargo.toml` with `cargo test`, `go.mod` with `go test`, or Python test configurations with `pytest`). Tests executable in the current stage SHALL execute and pass with exit code 0 before that stage advances, with coordinator-observed evidence containing the exact command, exit code, duration, output, environment, and candidate SHA. A test that cannot execute in the current stage solely because it requires unavailable, non-reproducible external infrastructure MAY remain pending for the corresponding project's GitHub Actions check on the implementation PR, only when the same test is configured to run there and the check result can be verified against the exact candidate head SHA. Such a test SHALL remain pending and SHALL NOT be represented as passed until that check succeeds; the workflow SHALL wait automatically for a conclusive result before implementation PR merge and SHALL not create a human gate merely to request that the test be run. Missing test-database configuration, unsafe database targeting, absent CI coverage, unavailable CI evidence, or failed checks SHALL NOT qualify for deferral or passing. The system SHALL reject skipped, mocked-out/vacuous, failed, or empty test execution as a passing result. When test selection or discovery cannot identify a supported test suite, the diagnostic failure SHALL accurately report the technology inspectable in the candidate worktree and SHALL NOT falsely report that Python or `pytest` was expected or omitted.

#### Scenario: Implementation includes passing unit and E2E tests with real test runner execution
- **GIVEN** the implementer completes source changes and writes corresponding unit, integration, or E2E tests executable in the current stage
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** it executes the changed tests and relevant tests mapped to the changed source files, without invoking the complete project suite
- **AND** it preserves the exact test command, exit code, captured output, and candidate SHA as observable evidence
- **AND** it advances only when the selected tests execute and pass with exit code 0.

#### Scenario: Unrelated pre-existing test failure is outside the focused gate
- **GIVEN** the candidate change modifies one code area and an unrelated, pre-existing test fails outside the selected set
- **WHEN** the Apply/Verify automated test gate runs
- **THEN** the unrelated test is not run by that gate
- **AND** the focused gate's result is determined by the selected tests and their captured execution evidence.

#### Scenario: No relevant tests cannot produce a passing result
- **GIVEN** changed executable code has no tests selected by the documented mapping and no changed tests are present
- **WHEN** the Apply/Verify automated test gate attempts to execute its selection
- **THEN** it records that no tests were selected or collected
- **AND** it does not treat the empty selection as a passing test result or fall back to the complete suite.

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
- **AND** it advances only when every executable check passes or every deferred check has an authorized same-SHA CI path and is tracked as pending.

#### Scenario: Integration test is deferred to matching project CI
- **GIVEN** a selected integration test requires external infrastructure unavailable in the current stage
- **AND** the project's implementation PR workflow is configured to execute that same test against an isolated test database
- **WHEN** Apply or Verify assesses the test
- **THEN** the test remains explicitly pending for the PR check and does not create a human gate
- **AND** the workflow retains the check identity and candidate SHA needed to match the result
- **AND** a passing check is not recorded until GitHub reports a conclusive success for that exact head SHA.

#### Scenario: Missing or failed deferred CI result blocks merge without a test gate
- **GIVEN** one or more tests are pending for the implementation PR CI check
- **WHEN** the required check is absent, pending, failed, or cannot be observed for the exact candidate head SHA
- **THEN** mini me does not mark those tests complete or merge the implementation PR
- **AND** it waits or reports the specific CI evidence failure through the existing observable workflow state without asking a human to execute an automatable test.

#### Scenario: Honest diagnostic on unsupported or missing test suite
- **GIVEN** a candidate change in a project lacking recognizable test manifests or configured checks
- **WHEN** the Apply/Verify automated test gate attempts execution
- **THEN** it halts fail-closed
- **AND** its failure diagnostic accurately describes the missing test declaration without attributing the failure to pytest unless Python test artifacts are genuinely present.

#### Scenario: Failing tests trigger immediate self-correction loop
- **GIVEN** the Apply/Verify automated test gate runs the selected tests
- **WHEN** a selected test fails or returns a non-zero exit code
- **THEN** the existing Apply self-correction flow receives the observed failure evidence
- **AND** the change does not advance until a subsequent focused execution passes.
