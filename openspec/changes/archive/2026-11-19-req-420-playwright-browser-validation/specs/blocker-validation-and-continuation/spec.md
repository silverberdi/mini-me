# blocker-validation-and-continuation Specification

## ADDED Requirements

### Requirement: Browser-test failures use correction or technical environment outcomes
An executed browser test failure SHALL enter the existing evidence-based correction path and SHALL NOT by itself create `HUMAN_REQUIRED`. If Playwright or Chromium is absent or unusable in the configured base execution runtime, mini me SHALL report an observable technical environment failure using the existing environment-unavailable handling, including the failed command and concrete missing capability. It SHALL NOT convert infrastructure failure into an operator test task, invent a new operational state, or treat the test as passed.

#### Scenario: Executed browser assertion fails
- **GIVEN** the browser command ran and returned a non-zero result for a test assertion
- **WHEN** mini me evaluates the result
- **THEN** the failure evidence is sent through the existing correction path
- **AND** no human gate asks the operator to rerun that browser check.

#### Scenario: Chromium is missing from the execution runtime
- **GIVEN** the test runner is declared but the configured runtime cannot locate or launch Chromium
- **WHEN** mini me preflights or invokes the browser test
- **THEN** it records an environment-unavailable technical blocker with the missing executable/runtime detail
- **AND** it does not ask the operator to perform the test or claim that the acceptance criterion passed.
