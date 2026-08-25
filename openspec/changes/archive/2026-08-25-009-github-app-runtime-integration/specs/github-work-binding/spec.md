## ADDED Requirements

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
