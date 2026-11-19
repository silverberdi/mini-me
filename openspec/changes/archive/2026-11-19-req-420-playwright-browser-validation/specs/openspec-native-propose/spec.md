# openspec-native-propose Specification

## ADDED Requirements

### Requirement: Native Propose receives observed project test-tool context
Before dispatching the configured thinking agent to native OpenSpec Propose and feasibility assessment, mini me SHALL provide a read-only inventory of configured checks and test tooling declared in the candidate repository's `package.json`, `pyproject.toml`, and `Makefile`, including relevant existing test scripts and the observable Playwright/Chromium runtime capability. It SHALL NOT execute package hooks or infer undeclared dependencies, and it SHALL NOT add a project-onboarding installer or database metadata for this inventory.

#### Scenario: Proposal uses existing browser test tooling
- **GIVEN** a repository declares a Playwright test script in `package.json` and its execution runtime exposes Chromium
- **WHEN** the thinking agent proposes a UI change
- **THEN** the native proposal receives those observed commands and runtime facts
- **AND** it does not invent another browser package, install flow, or operator-run test.

#### Scenario: Repository has no declared test runner
- **GIVEN** the repository has no configured checks or recognized test command in the inspected manifests
- **WHEN** the thinking agent proposes a change
- **THEN** mini me reports the absent evidence accurately
- **AND** it does not claim a particular dependency is installed or turn that absence into an operator task.

### Requirement: Browser-reproducible UI work belongs to the executor
The feasibility assessment SHALL assign validation of UI behavior reproducible in a real browser to the configured execution agent in the ordinary Apply or Verify stage. It SHALL NOT assign such a task to the operator or `human_validation`. Human tasks MAY remain for an actual human decision or physical-device-only evidence, scheduled after merge so they do not block automated browser work or its delivery.

For each acceptance scenario, the assessment SHALL identify its verification mode (`browser`, `physical_device`, `human_decision`, or `other`). The existing feasibility validator SHALL reject a `browser` scenario mapped outside an executor-owned Apply/Verify task, and SHALL keep `physical_device` and `human_decision` scenarios operator-owned at `human_validation`.

#### Scenario: Browser-reproducible acceptance scenario is feasible
- **GIVEN** an acceptance scenario covers navigation, responsive viewports, asynchronous UI state, or concurrent browser sessions that Playwright can reproduce
- **WHEN** feasibility assesses its OpenSpec task mapping
- **THEN** the task is assigned to the configured executor for Apply or Verify with observable browser evidence
- **AND** the scenario does not create a `HUMAN_REQUIRED` test gate.

#### Scenario: Physical-device evidence is distinct from browser evidence
- **GIVEN** a criterion requires hardware behavior that browser emulation cannot establish
- **WHEN** the proposal assigns its verification
- **THEN** it is identified as a post-merge physical-device follow-up
- **AND** it is not represented as a prerequisite to executing or completing browser-automatable tasks.

#### Scenario: Browser scenario is mapped to an operator
- **GIVEN** the feasibility report classifies an acceptance scenario as browser-reproducible
- **WHEN** it maps that scenario to an operator or a stage outside Apply/Verify
- **THEN** the existing feasibility validator rejects the inconsistent mapping for correction
- **AND** it does not represent the browser check as a human test gate.
