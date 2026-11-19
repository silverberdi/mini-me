# openspec-native-apply-and-verify Specification

## ADDED Requirements

### Requirement: Executor runs browser-reproducible UI acceptance with Playwright
For browser-reproducible UI acceptance scenarios, the configured executor SHALL create or update tests in the repository's existing conventions and execute them through the project's declared runner during Apply or Verify. The test SHALL exercise the served candidate in a real Playwright browser, not substitute mocked browser assertions for end-to-end evidence. The result SHALL preserve the exact command, exit code, relevant output, and full candidate SHA. The runner SHALL use declared project checks and scripts from existing manifests; it SHALL NOT add a Mini Me Playwright wrapper, per-project installer orchestration, database table, or service.

#### Scenario: Playwright scenario passes against the candidate
- **GIVEN** a candidate contains a browser-reproducible UI acceptance criterion and a declared Playwright runner
- **WHEN** the executor runs the corresponding Apply or Verify task
- **THEN** the actual application candidate is exercised in Chromium through browser interactions
- **AND** the invocation, successful exit code, output, and candidate SHA are available as evidence.

#### Scenario: Browser test fails
- **GIVEN** the Playwright command executes and reports a failed assertion
- **WHEN** Apply or Verify processes the result
- **THEN** the failure and output are returned to the existing correction workflow
- **AND** the operator is not asked to repeat the browser test manually.

#### Scenario: Physical-device check remains deferred
- **GIVEN** browser tests pass but a follow-up requires a physical phone or tablet
- **WHEN** the executor completes the automated browser criteria
- **THEN** that follow-up remains identified as post-merge physical validation
- **AND** it is neither marked as passed nor used to block the automated Apply/Verify tasks.

### Requirement: Browser capability is available in the base execution runtime
The standard execution runtime SHALL expose the supported Playwright driver and Chromium browser before project work is admitted. Availability SHALL be observable without installing browser dependencies for each project or ticket.

#### Scenario: Base browser runtime is ready
- **GIVEN** the configured execution runtime has its supported Playwright/Chromium installation
- **WHEN** a browser test is dispatched
- **THEN** the executor can invoke it using the repository's declared test command without an onboarding-time browser installation.
