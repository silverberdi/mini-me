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

### Requirement: Single-Pass Test Import Mapping
For each focused test-selection operation, the system SHALL parse each candidate pytest file's imports at most once and SHALL build an inverse module-to-tests index for direct imports. It SHALL use that index to find tests for changed source modules and SHALL NOT re-parse every test file for each changed module. Existing test path and module-name matching behavior SHALL remain unchanged.

#### Scenario: Import mapping indexes each test file once
- **GIVEN** a candidate has multiple changed source modules and multiple candidate pytest files
- **WHEN** the test selector builds direct-import relationships
- **THEN** it parses each candidate pytest file's AST once and records its imported modules in an inverse module-to-tests index
- **AND** it looks up each changed source module in that index without re-parsing test files
- **AND** it retains the existing test path, module-name, and direct-import selection results

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
For high-complexity changes, the configured independent reviewer agent SHALL receive a read-only prompt containing the Request, approved proposal, specifications, code, the complete candidate diff without truncation, and test evidence. The reviewer SHALL NOT modify code or execute OpenSpec workflows, and SHALL evaluate requirement fulfillment, functional correctness, security, and scope. The review prompt SHALL require findings to use these severities: BLOCKER means the change cannot be implemented safely; MAJOR means a real correctness or security gap; MINOR means a non-blocking nit. The reviewer SHALL focus on new, material defects, SHALL NOT re-flag requirements already covered, and SHALL NOT request wording or formatting changes. Python coordinator code SHALL NOT return static `True` stubs.

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

#### Scenario: Reviewer receives the complete candidate diff
- **GIVEN** a high-complexity candidate whose diff exceeds 4,000 characters
- **WHEN** the independent code review prompt is prepared
- **THEN** the prompt includes the complete candidate diff without truncation.

#### Scenario: Code review findings converge on substantive defects
- **GIVEN** a high-complexity candidate under independent code review
- **WHEN** the reviewer evaluates its requirements, implementation, and complete diff
- **THEN** it reports only new, material correctness, security, or scope defects
- **AND** assigns BLOCKER, MAJOR, or non-blocking MINOR according to the stated severity definitions
- **AND** does not re-flag requirements already covered or request wording or formatting changes.

### Requirement: Guided Recovery of Partial OpenSpec Apply
When native Apply leaves automatic tasks incomplete without a terminal failure or human-required question, the system SHALL evaluate recovery from coordinator-observed evidence and, when progress is observable, retry the native workflow on the same Change, branch, worktree, and candidate. The structured outcome SHALL include completed and pending automatic tasks, candidate SHA/fingerprint, errors, blockers, and original human-required questions and options. Git SHALL provide changed-file and diff evidence, and the coordinator SHALL provide test results; agent self-report alone SHALL NOT establish task completion. A task may be marked `[x]` only when observed diff and passing relevant tests support completion. Recovery instructions SHALL describe observed prior work and pending work, direct the agent to mark supported completed tasks and preserve valid work, and remain distinct from reviewer findings supplied via `corrections`. Native Continue SHALL be used only when the workflow permits direct resumption. The hard limit of three Apply attempts and the no-progress limit SHALL apply per automatic recovery cycle. When an accepted response to an Apply exhaustion gate authorizes continuation, the system SHALL start a new cycle at 0/3 attempts and reset that cycle's no-progress count to zero; it SHALL retain all prior invocation outcomes and the operator decision as immutable audit evidence. The human response SHALL NOT count as an Apply attempt. Retries SHALL respect correction and budget limits and SHALL stop fail-closed on worktree, branch, or run identity change or observed regression. Verify SHALL run only after evidence-backed completion or native readiness.

#### Scenario: Partial Apply with progress is retried on the same candidate
- **GIVEN** native Apply leaves automatic tasks pending without terminal failure or human-required question
- **AND** pending task count decreased or candidate SHA/fingerprint changed with a non-empty diff since the previous attempt
- **WHEN** the coordinator prepares another native Apply invocation
- **THEN** it supplies factual task, Git, test, error, and prior-work context
- **AND** directs the agent to mark `[x]` only tasks supported by observed diff and passing relevant tests
- **AND** preserves valid work and keeps reviewer `corrections` separate
- **AND** reuses the same Change, branch, worktree, and candidate.

#### Scenario: Human-required question is preserved without consuming retry
- **GIVEN** native Apply returns a genuine `HUMAN_REQUIRED` question with options
- **WHEN** the coordinator handles the result
- **THEN** it presents the original question and options to the operator
- **AND** does not count it as a retry.

#### Scenario: Native Continue is limited to resumable operations
- **GIVEN** a partial Apply result
- **WHEN** the native workflow permits direct resumption
- **THEN** the coordinator may invoke native Continue
- **AND** otherwise uses a guided native Apply retry.

#### Scenario: An accepted Apply gate response starts a fresh bounded cycle
- **GIVEN** Apply recovery has stopped at its human gate after three attempts in the current cycle
- **WHEN** the operator's response is accepted and authorizes continuation
- **THEN** the next Apply recovery cycle begins with 0/3 attempts and zero no-progress attempts
- **AND** the prior cycle's attempts, results, and operator response remain available as historical evidence
- **AND** the same Run, Change, branch, worktree, and candidate identity are retained
- **AND** the human response itself is not counted as an Apply attempt.

#### Scenario: Retry limits and regression stop recovery
- **GIVEN** Apply remains incomplete in the current recovery cycle
- **WHEN** no-progress or three-attempt hard limits are reached, or worktree, branch, or run identity changes, or observed valid files, supported completed tasks, or passing tests regress
- **THEN** automatic retries stop and the candidate and evidence are preserved for escalation
- **AND** configured correction and budget limits are respected.

#### Scenario: Verify waits for Apply readiness
- **GIVEN** automatic tasks remain without evidence-backed completion
- **AND** the native workflow has not declared Apply ready
- **WHEN** the coordinator evaluates the candidate
- **THEN** Verify is not dispatched.

#### Scenario: Simulated partial Apply recovery is deterministic
- **GIVEN** a deterministic simulated Apply runner returns a partial result followed by a completed result
- **WHEN** the recovery path is exercised
- **THEN** the retry receives observed corrective context and retains the candidate and worktree identity
- **AND** the simulated result is not represented as a real-agent invocation.

### Requirement: Apply preserves validation disposition and evidence provenance
Apply and Verify SHALL interpret validation tasks according to the strictly validated, currently active OpenSpec Change. A task explicitly deferred by an operator-authorized native Update SHALL remain visibly deferred or pending and SHALL NOT be marked complete without its required evidence. Evidence reported for a published version SHALL retain that source identity and SHALL NOT satisfy a candidate-specific criterion unless its immutable SHA is proven to match the candidate under review. Apply MAY continue with other work only when the updated Change permits it; Verify and PR readiness SHALL follow the updated acceptance criteria and fail closed when required evidence remains absent.

#### Scenario: Published-version evidence is not attributed to the candidate
- **GIVEN** the operator reports a validation performed on a published version
- **AND** that version's immutable SHA is absent or differs from the candidate SHA
- **WHEN** the coordinator records and evaluates the evidence
- **THEN** it identifies the evidence as belonging to the published version
- **AND** does not mark a candidate-specific task complete or claim candidate validation
- **AND** identifies the candidate evidence still required.

#### Scenario: Deferred criterion remains distinct from completed work
- **GIVEN** the operator-authorized OpenSpec Update explicitly defers a validation criterion
- **WHEN** native Apply processes the updated Change
- **THEN** it preserves the criterion's deferred/pending disposition and continues only with remaining work allowed by the updated Change
- **AND** it does not count the criterion as completed or as Apply progress
- **AND** Verify or PR preparation remains blocked if the updated acceptance criteria still require that evidence.

#### Scenario: No safe continuation from updated criteria
- **GIVEN** updated artifacts are invalid, ambiguous about whether deferred evidence gates completion, or inconsistent with the operator's explicit decision
- **WHEN** Apply or Verify evaluates readiness
- **THEN** it preserves the candidate and evidence and reports the exact unresolved criterion
- **AND** does not silently drop the criterion, mark it complete, or spend another Apply attempt on a generic retry.
