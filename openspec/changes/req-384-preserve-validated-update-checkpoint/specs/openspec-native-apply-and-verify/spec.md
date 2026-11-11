## MODIFIED Requirements

### Requirement: Guided Recovery of Partial OpenSpec Apply
When native Apply leaves automatic tasks incomplete without a terminal failure or human-required question, the system SHALL evaluate recovery from coordinator-observed evidence and, when progress is observable, retry the native workflow on the same Change, branch, worktree, and candidate. The structured outcome SHALL include completed and pending automatic tasks, candidate SHA/fingerprint, errors, blockers, and original human-required questions and options. Git SHALL provide changed-file and diff evidence, and the coordinator SHALL provide test results; agent self-report alone SHALL NOT establish task completion. A task may be marked `[x]` only when observed diff and passing relevant tests support completion. Recovery instructions SHALL describe observed prior work and pending work, direct the agent to mark supported completed tasks and preserve valid work, and remain distinct from reviewer findings supplied via `corrections`. Native Continue SHALL be used only when the workflow permits direct resumption. The hard limit of three Apply attempts and the no-progress limit SHALL apply per automatic recovery cycle. When an accepted response to an Apply exhaustion gate authorizes continuation, the system SHALL start a new cycle at 0/3 attempts and reset that cycle's no-progress count to zero; SHALL retain all prior invocation outcomes and the operator decision as immutable audit evidence. The human response SHALL NOT count as an Apply attempt. When a strictly validated native Update changes task dispositions before continuation, recovery SHALL reconcile only those explicitly changed dispositions against the validated Update checkpoint; all unaffected task progress and candidate identity SHALL remain subject to existing regression checks. A continuation-only response at a later Apply gate SHALL reuse the still-valid checkpoint and SHALL NOT replace it with an empty no-op Update result. Retries SHALL respect correction and budget limits and SHALL stop fail-closed on worktree, branch, or run identity change or observed regression.

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

#### Scenario: Authorized task reclassification is not treated as Apply regression
- **GIVEN** an accepted operator response causes a native OpenSpec Update that strictly validates for the same Run, Change, branch, worktree, and candidate
- **AND** the validated Update explicitly reclassifies one or more task dispositions
- **WHEN** Apply recovery compares the next outcome with its prior checkpoint
- **THEN** only the explicitly reclassified task dispositions are reconciled to the validated Update checkpoint
- **AND** regressions in unaffected task dispositions, candidate identity, changed-file evidence, or test results still stop recovery fail-closed.

#### Scenario: Continuation-only retry preserves the prior validated reclassification
- **GIVEN** a prior human-authorized native Update strictly validated one or more task reclassifications for the current Run, Change, branch, worktree, and candidate
- **AND** the subsequent Apply gate response only authorizes continuation and does not change criterion dispositions
- **WHEN** Apply recovery starts the next cycle
- **THEN** it reuses the prior validated reclassification checkpoint without dispatching a no-op native Update
- **AND** it continues to fail closed on regressions outside the previously reclassified task IDs.

#### Scenario: Retry limits and regression stop recovery
- **GIVEN** Apply remains incomplete in the current recovery cycle
- **WHEN** no-progress or three-attempt hard limits are reached, or worktree, branch, or run identity changes, or observed valid files, supported completed tasks, or passing tests regress outside a validated reclassification
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
