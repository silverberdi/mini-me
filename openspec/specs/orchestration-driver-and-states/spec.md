# Spec: Orchestration Driver and States

## Requirement: Complete Deterministic State Transitions
The orchestration driver SHALL support all canonical states and handle remediation transitions without entering undefined or dead-end states.

### Scenarios

#### Scenario: Checks Failure Remediation Route
- GIVEN a candidate execution whose deterministic checks fail,
- WHEN `RUNNING_CHECKS` completes with non-zero exit codes,
- THEN the run SHALL transition to `EVALUATING_ATTEMPT` and route to `IMPLEMENTING` for bounded corrective retry.

#### Scenario: Review Changes Required Route
- GIVEN a complementary review that returns structured verdict `CHANGES_REQUIRED`,
- WHEN `COMPLEMENTARY_REVIEW` evaluates the verdict,
- THEN the run SHALL transition to `REVIEW_REMEDIATION` and route back to `IMPLEMENTING` with the review findings formatted into the implementer context.

#### Scenario: DeepSeek Audit Blocked Route
- GIVEN a DeepSeek audit that reports CRITICAL or HIGH severity findings,
- WHEN `INDEPENDENT_AUDIT` evaluates the audit report,
- THEN the run SHALL transition to `AUDIT_REMEDIATION` and route back to `IMPLEMENTING` with the audit findings formatted into the implementer context.

#### Scenario: Terminal Stop at READY_FOR_HUMAN_MERGE
- GIVEN a candidate that has passed checks, review, and audit, and whose PR is prepared,
- WHEN `PR_PREPARED` completes,
- THEN the run SHALL stop with `stop_outcome=READY_FOR_HUMAN_MERGE` and `human_gate=READY_FOR_HUMAN_MERGE`.
