## Purpose
Execute end-to-end implementation and automated test verification through official OpenSpec Apply and Verify workflows, managing self-correction loops and independent code review for high-complexity changes.

## ADDED Requirements

### Requirement: Full End-to-End OpenSpec Apply Execution
The configured implementer agent SHALL recover the exact candidate branch, worktree, and Change name, SHALL invoke the official installed OpenSpec Apply workflow (`/opsx-apply` or `$openspec-apply-change`), and SHALL complete implementation from beginning to end without artificial pauses or requesting continuation OKs for partial deliverables.

#### Scenario: Implementer executes complete task set
- **WHEN** the change reaches `READY TO APPLY`
- **THEN** the implementer agent is dispatched in the confined worktree and executes all implementation tasks defined in `tasks.md`.

#### Scenario: Material specification drift triggers return to propose
- **WHEN** implementation reveals that the approved specification requires substantive modification
- **THEN** the system stops Apply and routes the change back to the native Propose/Validate loop instead of permitting silent spec modifications.

### Requirement: Mandatory Real Unit and E2E Test Execution
The implementer agent SHALL design, execute, and verify real unit and E2E tests within the project's testing conventions and environment, SHALL autocorrect test and code defects during Apply, and SHALL emit `READY TO VERIFY` only after all tests pass with exit code 0 and observable test evidence is preserved.

#### Scenario: Implementation includes passing unit and E2E tests
- **WHEN** the implementer completes source code modifications
- **THEN** the agent writes corresponding tests in `tests/`, executes the project test suite (e.g. `pytest`), and ensures 100% of required checks pass.

#### Scenario: Failing tests trigger immediate self-correction
- **WHEN** test execution produces errors or assertion failures during Apply
- **THEN** the implementer analyzes the failure output, adjusts code or test logic, and re-executes tests until green before completing Apply.

### Requirement: Native OpenSpec Verify Executed by Implementer
The system SHALL invoke the official OpenSpec Verify workflow using the SAME implementer agent that executed Apply (and NOT the thinking agent), utilizing the verified project context and preflighted capacity.

#### Scenario: Implementer executes official verify workflow
- **WHEN** Apply finishes with passing tests
- **THEN** mini me instructs the implementer agent to run the official OpenSpec Verify workflow in the candidate worktree.

### Requirement: Verify Failure Feedback Loop
If OpenSpec Verify fails, the system SHALL extract the authentic findings report, deliver it as context to the implementer agent in an official OpenSpec Apply correction prompt, re-execute the test suite, and re-run Verify up to the project's configured correction limit without human intervention.

#### Scenario: Verify failure initiates automatic correction pass
- **WHEN** OpenSpec Verify reports specification discrepancies or incomplete tasks
- **THEN** the findings report is provided to the implementer in an Apply correction prompt, fixes are applied, tests are re-run, and Verify is repeated.

### Requirement: Post-Verify Complexity Routing
Upon successful completion of OpenSpec Verify, the system SHALL evaluate the change complexity determined during Propose: changes of low or moderate complexity SHALL transition directly to `READY FOR PR`, whereas changes of high complexity SHALL transition to `READY FOR INDEPENDENT REVIEW`.

#### Scenario: Low or moderate complexity transitions to ready for pr
- **WHEN** Verify succeeds for a change of low or moderate complexity
- **THEN** the operational stage emits `READY FOR PR` with code review marked unnecessary.

#### Scenario: High complexity transitions to independent review
- **WHEN** Verify succeeds for a change of high complexity
- **THEN** the operational stage emits `READY FOR INDEPENDENT REVIEW` for implementation review.

### Requirement: Independent Implementation Code Review for High Complexity
For high-complexity changes, the configured independent reviewer agent SHALL receive a read-only prompt containing the Request, approved proposal, specifications, code, diff, and test evidence, SHALL NOT modify code or execute OpenSpec workflows, and SHALL evaluate requirement fulfillment, functional correctness, security, maintainability, and absence of overengineering.

#### Scenario: Independent reviewer approves implementation
- **WHEN** the independent reviewer determines the implementation satisfies all criteria without overengineering
- **THEN** the review is recorded as APPROVED and the change emits `READY FOR PR`.

#### Scenario: Independent reviewer rejects with actionable findings
- **WHEN** the independent reviewer identifies functional flaws, regressions, or security vulnerabilities
- **THEN** the reviewer outputs concrete, actionable findings, and the system routes the change back to the implementer via OpenSpec Apply -> Verify -> Independent Review until approved or until the iteration limit is reached.
