## ADDED Requirements

### Requirement: Guided Recovery of Partial OpenSpec Apply
When native Apply leaves automatic tasks incomplete without a terminal failure or human-required question, the system SHALL evaluate recovery from coordinator-observed evidence and, when progress is observable, retry the native workflow on the same Change, branch, worktree, and candidate. The structured outcome SHALL include completed and pending automatic tasks, candidate SHA/fingerprint, errors, blockers, and original human-required questions and options. Git SHALL provide changed-file and diff evidence, and the coordinator SHALL provide test results; agent self-report alone SHALL NOT establish task completion. A task may be marked `[x]` only when observed diff and passing relevant tests support completion. Recovery instructions SHALL describe observed prior work and pending work, direct the agent to mark supported completed tasks and preserve valid work, and remain distinct from reviewer findings supplied via `corrections`. Native Continue SHALL be used only when the workflow permits direct resumption. Retries SHALL stop at configured no-progress and hard total-attempt limits, respecting correction and budget limits, and SHALL stop fail-closed on worktree, branch, or run identity change or observed regression. Verify SHALL run only after evidence-backed completion or native readiness.

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

#### Scenario: Retry limits and regression stop recovery
- **GIVEN** Apply remains incomplete
- **WHEN** no-progress or hard total-attempt limits are reached, or worktree, branch, or run identity changes, or observed valid files, supported completed tasks, or passing tests regress
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
