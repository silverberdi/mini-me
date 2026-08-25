# GitHub Work Binding Specification

## Purpose
Provide durable GitHub work-tracking identifiers while ensuring presentation metadata never becomes execution authority.

## Requirements

### Requirement: Durable GitHub identifiers
The system SHALL persist repository Issue and global Project item identifiers associated with a project/change without using their display text as execution identity.

#### Scenario: Persist GitHub work identifiers without display-name authority
- **GIVEN** a registered project and discovered OpenSpec change
- **WHEN** a GitHub Issue and global Project item are associated with that change
- **THEN** their durable identifiers are persisted with the project/change binding
- **AND** issue titles, labels, Project fields, or display names do not become execution identity.

### Requirement: GitHub outage does not corrupt internal state
A GitHub synchronization or PR preparation failure SHALL be observable and reconcilable without deleting durable project/change/orchestration state, creating duplicate external work, or authorizing a PR whose head differs from the final independently audited candidate.

#### Scenario: PR creation is idempotent
- **GIVEN** a final candidate has passed all required checks, review, and audit
- **WHEN** orchestration prepares the GitHub PR more than once because of retry or restart
- **THEN** the integration uses a durable idempotency identity and reconciles one PR bound to the project/change and exact audited head SHA.

#### Scenario: GitHub is temporarily unavailable
- **GIVEN** internal evidence is complete but GitHub cannot be reached
- **WHEN** PR preparation fails transiently
- **THEN** the run preserves all internal evidence and stops in `WAITING_EXTERNAL` without marking the candidate ready for human merge.

#### Scenario: Unexpected remote identity is detected
- **WHEN** repository, base branch, PR binding, or remote head SHA differs from the durable project binding or audited candidate
- **THEN** the system records a structured invariant failure and stops for human attention without changing the binding or pushing a different candidate.

#### Scenario: External action reservation precedes mutation
- **WHEN** orchestration requests a branch push or PR create/update
- **THEN** a durable action identity, target identity, and request fingerprint are reserved and committed before the GitHub/Git mutation; failure to reserve prevents the mutation.

#### Scenario: GitHub synchronization is temporarily unavailable
- **GIVEN** durable project/change state already exists
- **WHEN** GitHub synchronization fails transiently
- **THEN** internal state remains intact and the synchronization failure is recorded for later reconciliation.

### Requirement: Remote Issue existence and repository ownership validation
The system SHALL verify through the authenticated GitHub API under the GitHub App runtime identity that a bound Issue exists and belongs strictly to the registered repository defined in the durable ProjectBinding.

#### Scenario: Issue exists in bound repository
- **GIVEN** a durable project binding with a GitHub issue number
- **WHEN** the GitHub adapter validates the issue binding against GitHub
- **THEN** the issue is fetched from the bound repository via the GitHub App API
- **AND** the validation succeeds only if the issue exists in that exact repository.

#### Scenario: Issue belongs to another repository
- **GIVEN** an issue number that exists only in a different repository or is supplied with conflicting repository metadata
- **WHEN** the GitHub adapter validates the issue binding
- **THEN** the validation fails closed with a structured repository mismatch error
- **AND** the change is marked NOT_READY with explicit mismatch details.

#### Scenario: Issue does not exist
- **GIVEN** an issue number that does not exist in the bound remote repository (404 Not Found)
- **WHEN** the GitHub adapter validates the issue binding
- **THEN** the validation fails closed with a structured nonexistent issue error.

#### Scenario: GitHub API is unobservable during issue validation
- **GIVEN** GitHub is unreachable, rate limited, or experiencing an outage during issue validation
- **WHEN** issue validation is evaluated
- **THEN** the result is marked as transiently unobservable
- **AND** the failure is distinguishable from a permanent contradiction or mismatch.

### Requirement: Authoritative PR lifecycle under App identity
The system SHALL execute all PR lookups, verifications, and creations directly against the GitHub REST API using the GitHub App installation identity, strictly enforcing authoritative PR lookup states.

#### Scenario: PR lookup returns NOT_FOUND
- **GIVEN** no pull request exists for the change branch against the base branch
- **WHEN** PR lookup executes under the GitHub App identity
- **THEN** the adapter returns state `NOT_FOUND`
- **AND** only this state authorizes new PR creation.

#### Scenario: PR lookup returns FOUND_EXACT matching candidate
- **GIVEN** an existing PR matches the target repository, head branch, base branch, and exact audited candidate SHA
- **WHEN** PR lookup executes
- **THEN** the adapter returns state `FOUND_EXACT` with authoritative PR metadata for adoption.

#### Scenario: PR lookup returns UNOBSERVABLE
- **GIVEN** GitHub API returns a network error, 5xx server error, or rate limit
- **WHEN** PR lookup executes
- **THEN** the adapter returns state `UNOBSERVABLE`
- **AND** orchestration stops in `WAITING_EXTERNAL` without creating a duplicate PR.

#### Scenario: PR lookup returns AMBIGUOUS
- **GIVEN** multiple plausible PRs exist or the remote payload cannot be resolved uniquely
- **WHEN** PR lookup executes
- **THEN** the adapter returns state `AMBIGUOUS`
- **AND** orchestration fails closed to `NEEDS_HUMAN`.

#### Scenario: PR creation verifies created PR head equality
- **GIVEN** PR lookup returned `NOT_FOUND` and a new PR is created via the GitHub API
- **WHEN** the creation response is received
- **THEN** the adapter verifies the returned PR head SHA equals the audited candidate SHA before marking the action completed.
