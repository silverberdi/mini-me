# Domain Model

## Project
Immutable internal `project_id` plus repository identity and project-level policies. Human-readable names are display metadata only.

## Change
Durable representation of a GitHub Issue + OpenSpec change bound to one registered project.

## Job
Operational execution of a change through implementation/review/audit/deployment stages.

## Attempt
One invocation of a provider or external operation, with result classification and evidence.

## Candidate
Exact code/artifact identity under evaluation: repository, base SHA, head SHA, branch, optional container image digest.

## Review
Authoritative complementary review result. Reviewer identity must satisfy independence policy.

## Audit
Read-only DeepSeek Direct independent contradiction/risk layer.

## Human decision
Durable approval, request-changes, reject, ambiguity answer, budget authorization or rollback authorization.

## Validation session
Human UI validation tied to an exact candidate and the scenarios specified in OpenSpec.

## Deployment
Preview or production deployment with candidate/image identity, environment, timestamps and verification evidence.

## Event
Append-only explanation of externally meaningful state transition or decision.
