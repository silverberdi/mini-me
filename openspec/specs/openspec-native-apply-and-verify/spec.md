# openspec-native-apply-and-verify Specification

## Purpose
Execute end-to-end implementation and automated test verification through official OpenSpec Apply and Verify workflows, managing self-correction loops and independent code review for high-complexity changes.

## Requirements

### Requirement: Full End-to-End OpenSpec Apply Execution
The system SHALL dynamically resolve the official OpenSpec Apply workflow for the configured implementer agent based on the workflows installed in the worktree (`.agent/workflows/opsx-apply.md` for Antigravity or `.agents/skills/openspec-apply-change/SKILL.md` for Codex) using the resolution mechanics in `native_openspec_apply.py`. The configured implementer agent SHALL recover the exact candidate branch, worktree, and Change name, SHALL invoke the resolved workflow, and SHALL complete implementation from beginning to end without artificial pauses or requesting continuation OKs for partial deliverables. Coordinator code SHALL NOT emulate task execution via string replacements or synthetic file edits.

#### Scenario: Implementer executes complete task set end-to-end
- **GIVEN** a candidate change in `READY TO APPLY` status in an isolated worktree
- **AND** the implementer agent has verified native Apply workflow installed in the project worktree
- **WHEN** mini me dispatches the configured implementer agent via `CliAgentRunner` without synthetic task emulations
- **THEN** the implementer executes the native Apply workflow
- **AND** modifies the project files as specified in `tasks.md`
- **AND** preserves the commit history and branch identity.

#### Scenario: Material specification drift triggers return to propose
- **GIVEN** an implementer actively executing OpenSpec Apply in the candidate worktree
- **WHEN** implementation reveals that the approved specification requires substantive architectural or contract modifications
- **THEN** the system halts Apply immediately
- **AND** routes the change back to the native Propose/Validate loop instead of permitting silent or unreviewed spec modifications.

### Requirement: Mandatory Real Unit and E2E Test Execution
The implementer agent SHALL design, execute, and verify real unit and E2E tests within the project's testing conventions and environment, SHALL autocorrect test and code defects during Apply, and SHALL emit `READY TO VERIFY` only after all tests pass with exit code 0 and observable test evidence is preserved. The system SHALL reject any transition where tests were skipped, mocked out as vacuous stubs, or failed.

#### Scenario: Implementation includes passing unit and E2E tests with real test runner execution
- **GIVEN** the implementer agent completing source code changes in the candidate worktree
- **WHEN** the agent writes corresponding unit and integration tests under `tests/`
- **AND** invokes the project's authentic test suite runner (e.g. `pytest`) in the worktree environment
- **THEN** the test suite executes completely and exits with code 0
- **AND** the observable test output is captured in the execution run logs as durable evidence.

#### Scenario: Failing tests trigger immediate self-correction loop
- **GIVEN** the implementer agent executing tests during Apply
- **WHEN** test execution produces errors, failures, or non-zero exit codes
- **THEN** the implementer inspects the failure output and stack traces
- **AND** adjusts code or test logic in the candidate worktree
- **AND** re-executes the test suite until all tests succeed (exit code 0) before declaring Apply complete.

### Requirement: Native OpenSpec Verify Executed by Implementer with Capability Verification
The system SHALL verify that the configured implementer agent has the official OpenSpec Verify workflow installed and compatible in the candidate worktree (`.agent/workflows/opsx-verify.md` for Antigravity or `.agents/skills/openspec-verify-change/SKILL.md` for Codex) before dispatching. If the Verify workflow is missing or unverified, the system SHALL block fail-closed, report the missing capability, and preserve the Request. Upon successful Apply, the system SHALL invoke the official OpenSpec Verify workflow using the SAME implementer agent that executed Apply (and NOT the thinking agent), utilizing the verified project context and preflighted capacity.

#### Scenario: Implementer executes official verify workflow with observable artifact verification
- **GIVEN** Apply finished with all tests passing (exit code 0) in the candidate worktree
- **AND** the presence of the native OpenSpec Verify workflow is verified in the worktree
- **WHEN** mini me dispatches the same implementer agent to execute native OpenSpec Verify
- **THEN** the agent executes the official Verify workflow
- **AND** inspects that implemented files and tests match the change specifications
- **AND** produces an authentic verification report without synthetic Python bypasses.

#### Scenario: Missing native Verify blocks execution fail-closed
- **GIVEN** an implementer agent ready to verify completed code
- **WHEN** the implementer profile lacks the verified native OpenSpec Verify workflow in the candidate worktree
- **THEN** mini me halts execution immediately fail-closed
- **AND** reports the specific missing capability
- **AND** preserves the candidate worktree, branch, and PostgreSQL run record intact
- **AND** prevents further stage transitions without fabricating replacements or guessing shell commands.

### Requirement: Verify Failure Feedback Loop
If OpenSpec Verify fails, the system SHALL extract the authentic findings report, deliver it as context to the implementer agent in an official OpenSpec Apply correction prompt, re-execute the test suite, and re-run Verify up to the project's configured correction limit without human intervention.

#### Scenario: Verify failure initiates automatic correction pass
- **GIVEN** OpenSpec Verify reporting specification discrepancies, missing requirements, or incomplete tasks
- **WHEN** the correction loop counter is below the configured max attempts
- **THEN** mini me extracts the authentic Verify findings report
- **AND** dispatches the implementer agent with an Apply correction prompt containing the exact report
- **AND** verifies that fixes are applied, test suite passes (exit code 0), and OpenSpec Verify is re-executed.

#### Scenario: Verify correction budget exhaustion halts execution cleanly
- **GIVEN** persistent OpenSpec Verify failures
- **WHEN** the correction attempts reach the configured project limit
- **THEN** mini me marks the run as blocked
- **AND** preserves the worktree, findings report, and execution logs for human inspection without discarding the Request.

### Requirement: Post-Verify Complexity Routing
Upon successful completion of OpenSpec Verify, the system SHALL evaluate the change complexity determined during Propose: changes of low or moderate complexity SHALL transition directly to `READY FOR PR`, whereas changes of high complexity SHALL transition to `READY FOR INDEPENDENT REVIEW`.

#### Scenario: Low or moderate complexity transitions to ready for pr
- **GIVEN** a verified change whose classified complexity is low or moderate
- **WHEN** OpenSpec Verify succeeds
- **THEN** the operational stage emits `READY FOR PR`
- **AND** records that independent code review is not required per policy.

#### Scenario: High complexity transitions to independent review
- **GIVEN** a verified change whose classified complexity is high
- **WHEN** OpenSpec Verify succeeds
- **THEN** the operational stage emits `READY FOR INDEPENDENT REVIEW`
- **AND** schedules independent code review by the distinct review agent.

### Requirement: Independent Implementation Code Review for High Complexity
For high-complexity changes, the configured independent reviewer agent SHALL receive a read-only prompt containing the Request, approved proposal, specifications, code, diff, and test evidence, SHALL NOT modify code or execute OpenSpec workflows, and SHALL evaluate requirement fulfillment, functional correctness, security, maintainability, and absence of overengineering. Python coordinator code SHALL NOT return static `True` stubs.

#### Scenario: Independent reviewer approves implementation with structured verdict
- **GIVEN** a high-complexity change in `READY FOR INDEPENDENT REVIEW`
- **AND** a distinct read-only reviewer agent configured in project settings
- **WHEN** mini me dispatches the reviewer agent with diff, specs, and test execution evidence
- **THEN** the reviewer evaluates the code without write permissions or branch modifications
- **AND** emits an APPROVED verdict with written justification
- **AND** the coordinator records the review result in PostgreSQL and advances to `READY FOR PR`.

#### Scenario: Independent reviewer rejects with actionable findings
- **GIVEN** a high-complexity change under independent review
- **WHEN** the reviewer detects missing requirements, architectural defects, security issues, or regressions
- **THEN** the reviewer emits a CHANGES REQUESTED verdict with specific, actionable findings
- **AND** mini me routes the change back to the implementer agent via Apply correction prompt
- **AND** requires green test execution and OpenSpec Verify re-check before re-submitting to the reviewer.
