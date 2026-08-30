# Preserved Candidate Remediation Specification

## ADDED Requirements

### Requirement: Explicit Human Authorization
The system SHALL require explicit human authorization before remediating a preserved candidate.

#### Scenario: Normal resume
Given a run stopped at `NEEDS_HUMAN`
When the user invokes normal resume
Then remediation SHALL NOT start.

#### Scenario: Explicit remediation
Given a valid current frozen candidate and valid contract
When explicit remediation is requested
Then eligibility SHALL be evaluated.

### Requirement: Current Candidate Authority
The latest non-superseded `OrchestrationCandidate` SHALL be the remediation source authority.

#### Scenario: Authority mismatch
Given any required run/job/candidate/Git authority differs
When remediation eligibility is evaluated
Then remediation SHALL fail closed before worktree creation or agent invocation.

### Requirement: Historical Admission Base Preservation
`run.base_sha` SHALL remain historical admission evidence.

#### Scenario: Previously integrated candidate
Given the current candidate base differs from `run.base_sha`
When remediation is evaluated
Then authority SHALL use the current candidate
And `run.base_sha` SHALL remain unchanged.

### Requirement: Immutable Remediation Contract
The system SHALL persist a structured immutable contract bound to exact source candidate identity.

#### Scenario: Contract replacement
Given an admitted remediation contract
When a different contract hash is supplied for the same operation
Then the admitted contract SHALL NOT be overwritten.

### Requirement: Scope Enforcement
Actual changed paths SHALL be within `allowed_paths` and outside `protected_paths`.

#### Scenario: Scope violation
Given an agent modifies a protected or non-allowed path
When scope validation runs
Then candidate finalization SHALL stop fail-closed
And the remediation workspace SHALL be preserved.

### Requirement: New Managed Remediation Generation
Authorized remediation SHALL create generation N+1 from current candidate SHA.

#### Scenario: Source immutability
Given generation N is remediated
When generation N+1 is created
Then generation N commit, ref, manifest, SHA, and base SHALL remain unchanged.

### Requirement: Base Advancement Safety
The system SHALL NOT silently remediate against a stale registered base.

#### Scenario: Base advanced
Given registered base differs from source candidate base
When remediation is requested
Then remediation SHALL stop with `BASE_ADVANCED_REQUIRES_INTEGRATION`.

### Requirement: System-Owned Finalization
mini me SHALL own authoritative candidate commit creation.

#### Scenario: No progress
Given the implementer produces no meaningful authorized change
When progress is evaluated
Then no new candidate generation SHALL be created.

### Requirement: Monotonic Candidate History
Failed remediation generations SHALL remain preserved and may become sources for later generations.

#### Scenario: Failed N+1
Given generation N+1 is finalized
And deterministic checks fail
When the run stops
Then N+1 SHALL remain preserved and current.

### Requirement: Complete Deterministic Check Evidence
Every configured deterministic check SHALL produce persisted evidence even if an earlier check fails.

#### Scenario: Unsafe disposable PostgreSQL check
Given a disposable PostgreSQL check fails safety validation
When checks execute
Then that check SHALL fail closed
And later configured checks SHALL still execute and persist evidence.

### Requirement: Candidate-Bound Evidence
All check evidence SHALL bind the exact remediation candidate SHA and generation.

#### Scenario: New remediation checks
Given generation N+1 candidate SHA S
When check results are persisted
Then each result SHALL reference generation N+1 and SHA S.

### Requirement: Correct Failure Classification
Git success followed by deterministic-check failure SHALL NOT be classified as a Git base conflict.

#### Scenario: Checks fail after successful Git operation
Given the Git operation succeeds
And deterministic checks fail
When the run stops
Then the stop code SHALL NOT be `BASE_INTEGRATION_CONFLICT`.

### Requirement: Idempotent Remediation
Repeated identical authorization SHALL not duplicate logical remediation work.

#### Scenario: Replay completed remediation
Given the same run ID, source generation, source SHA, and contract hash
And the remediation already completed
When the same authorization is replayed
Then the implementer SHALL NOT be invoked again
And no duplicate candidate generation SHALL be created.

### Requirement: Restart Safety
Remediation SHALL reconcile durable state and Git state after restart.

#### Scenario: Dirty remediation workspace
Given a remediation workspace is dirty
When restart recovery runs
Then the workspace SHALL NOT be force-deleted.

### Requirement: Review and Audit Generation Isolation
Review and audit evidence SHALL NOT carry across generations.

#### Scenario: Prior generation reviewed
Given generation N has review or audit evidence
When N+1 is created
Then generation N evidence SHALL NOT satisfy N+1 gates.

### Requirement: Dedicated Remediation Responsibility
Candidate remediation lifecycle SHALL live in a dedicated service/component rather than expanding the
preserved-candidate resolver monolith.

#### Scenario: Responsibility separation
Given candidate remediation is implemented
When architecture is inspected
Then orchestration coordination SHALL delegate remediation mechanics to a dedicated component.

### Requirement: Single Alembic Head
A remediation persistence migration SHALL extend the one current Alembic head.

#### Scenario: Migration added
Given main has one Alembic head
When the remediation migration is added
Then Alembic SHALL still report exactly one head.

### Requirement: End-to-End Recovery Proof
The change SHALL include real-Git end-to-end remediation acceptance tests.

#### Scenario: Historical candidate remediated
Given generation N is frozen at `NEEDS_HUMAN`
And an explicit valid remediation contract is supplied
When remediation completes successfully
Then N+1 SHALL be finalized with a new manifest and complete check evidence
And the current candidate SHALL be eligible for the next orchestration gate.

#### Scenario: Failed remediation remediated again
Given N+1 is preserved after failed checks
When a later explicit remediation is authorized
Then N+2 SHALL be creatable without mutating N or N+1.
