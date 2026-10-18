## ADDED Requirements

### Requirement: Checks-Only State Re-Entry Without Implementer Loop
The orchestration driver SHALL support entering `RUNNING_CHECKS` from an in-progress or interrupted run without transitioning through the `IMPLEMENTING` provider execution loop when recovering a preserved, unmutated candidate.

#### Scenario: Driver receives checks-only continuation directive
- **WHEN** `drive_coordinator()` is invoked with a valid claim context and an explicit checks-only directive
- **AND** the active job has a verified `candidate_sha` and worktree HEAD match
- **THEN** the coordinator SHALL transition directly to `RUNNING_CHECKS` via an authorized, fenced checks-only edge
- **AND** the coordinator SHALL consume the verified check results executed by the checks-only pipeline
- **AND** the coordinator SHALL NOT execute `pipeline.execute_queued_job()` or dispatch new implementer attempts.

#### Scenario: Checks pass and coordinator advances to freeze candidate
- **WHEN** `RUNNING_CHECKS` completes successfully under checks-only continuation
- **THEN** the driver SHALL advance the run to `FREEZING_CANDIDATE`
- **AND** the driver SHALL materialize the candidate manifest and persist the `OrchestrationCandidate` row.

### Requirement: Review Hold Without Automated Model Dispatch
When executing checks-only recovery, the coordinator SHALL halt execution immediately following candidate freezing, establishing a durable review-pending checkpoint without dispatching reviewer or auditor models.

#### Scenario: Candidate frozen halts at review hold
- **WHEN** candidate freezing completes under checks-only recovery
- **THEN** the driver SHALL stop with `stop_outcome=NEEDS_HUMAN`, `human_gate=HumanGate.NEEDS_HUMAN`, and `stop_details.code=REVIEW_AUTHORIZATION_PENDING`
- **AND** the driver SHALL NOT invoke DeepSeek or Antigravity code review or audit runners
- **AND** the driver SHALL set `is_active=False` and set BacklogItem status to `NEEDS_HUMAN`
- **AND** subsequent review execution SHALL require separate human authorization without replaying APPLY.
