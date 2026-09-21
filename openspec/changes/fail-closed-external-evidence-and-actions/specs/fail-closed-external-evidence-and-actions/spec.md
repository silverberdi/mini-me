# Spec: Fail-Closed External Evidence and Actions

## ADDED Requirements

### Requirement: Strongly typed external outcome model

The system SHALL represent all external adapter queries and mutating side effects using a strongly typed container (`ExternalActionResult[T]`) with explicit outcome states (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`), observed evidence payload, typed reason codes, and retry safety metadata.

#### Scenario: Successful external operation returns SUCCESS with observed data
GIVEN a valid external REST or CLI operation
WHEN the remote system returns an authoritative positive response
THEN the adapter SHALL return outcome SUCCESS
AND data SHALL contain the observed external payload
AND observed_evidence SHALL record postcondition confirmation.

#### Scenario: Unobservable or timed-out operation returns UNKNOWN or AMBIGUOUS
GIVEN an external operation invocation
WHEN the operation times out, returns HTTP 50x/429, or receives an unparseable response
THEN the adapter SHALL return outcome UNKNOWN or AMBIGUOUS
AND is_success SHALL evaluate to False.

### Requirement: Elimination of fabricated default success in production adapters

Production adapters SHALL NOT return synthetic identifiers (e.g. `issue #1`, `PVTI_mock_*`), dummy URLs, or default `True` boolean returns on exceptions or unobservable responses.

#### Scenario: Adapter method unavailable or unimplemented
GIVEN an external adapter method or provider interface
WHEN the underlying service or binary is unavailable or unimplemented
THEN the adapter SHALL return an explicit FAILURE or UNKNOWN outcome with reason code UNSUPPORTED
AND SHALL NOT return synthetic data or default True.

### Requirement: Fail-closed GitHub issue and project operations

All GitHub REST and CLI operations for issue creation, project binding, status updates, and issue closure SHALL execute fail-closed postcondition verification and return typed outcome reports.

#### Scenario: GitHub create_issue timeout after server request
GIVEN a request to create a GitHub Issue
WHEN network timeout occurs after POST request transmission
THEN GitHubAdapter SHALL return outcome AMBIGUOUS or UNKNOWN
AND SHALL NOT return synthetic issue #1 or fake HTML URL.

#### Scenario: GitHub create_issue hard 401/403 authorization error
GIVEN a request to create a GitHub Issue
WHEN GitHub API returns HTTP 401 or 403 authorization failure
THEN GitHubAdapter SHALL return outcome FAILURE with reason code AUTH_REQUIRED
AND SHALL NOT retry or fabricate success.

#### Scenario: GitHub add_issue_to_project CLI failure
GIVEN a request to add an issue to a GitHub Project V2
WHEN gh CLI execution fails or returns non-zero exit code
THEN GitHubAdapter SHALL return outcome FAILURE or UNKNOWN
AND SHALL NOT return a synthetic mock ID like PVTI_mock_2.

#### Scenario: GitHub close_issue encounters 404 or unobservable issue
GIVEN a request to close a GitHub Issue
WHEN GET issue check returns 404 Not Found or HTTP 500 error
THEN GitHubAdapter SHALL return outcome FAILURE (if 404) or UNKNOWN (if 500)
AND SHALL NOT return True on exception.

#### Scenario: GitHub close_issue on already-closed issue
GIVEN a request to close a GitHub Issue
WHEN GET issue check observes state == "closed"
THEN GitHubAdapter SHALL return outcome SUCCESS with reason code ALREADY_CLOSED
AND SHALL NOT issue duplicate PATCH requests.

#### Scenario: Already-existing issue deduplication
GIVEN a request to create a GitHub Issue with title T
WHEN pre-creation lookup observes an existing issue in repository R with identical title T
THEN GitHubAdapter SHALL return outcome SUCCESS with data set to the existing issue details
AND reason code SHALL be REUSED_EXISTING.

### Requirement: Fail-closed Git operations and ancestry verification

Git operations for ancestry, branch push, ls-remote, worktree cleanup, and branch deletion SHALL verify explicit return codes, stderr/stdout messages, and exact SHA/ref evidence.

#### Scenario: Git ancestry verification fails or cannot be established
GIVEN a candidate commit SHA and base reference
WHEN git merge-base --is-ancestor fails or encounters a missing/corrupted git reference
THEN ancestry verification SHALL return outcome UNKNOWN or FAILURE
AND SHALL NOT report merged or valid ancestry.

#### Scenario: Remote branch deletion command fails
GIVEN a request to delete a remote Git branch
WHEN git command or DELETE API fails with HTTP 500 or network timeout
THEN GitHubAdapter SHALL return outcome UNKNOWN or FAILURE
AND SHALL NOT report boolean True.

### Requirement: OpenSpec filesystem action postcondition verification

OpenSpec canonical spec sync and active change archiving SHALL confirm verifiable filesystem postconditions before reporting success.

#### Scenario: OpenSpec sync command succeeds but canonical spec missing
GIVEN an OpenSpec sync command execution
WHEN command exits code 0 but target spec.md is missing or lacks valid Requirements
THEN sync verification SHALL return outcome FAILURE or UNKNOWN
AND SHALL NOT report sync success.

#### Scenario: Archive directory move partially completes
GIVEN a request to archive an OpenSpec change
WHEN target directory creation or move fails before full directory migration
THEN archive operation SHALL return outcome AMBIGUOUS
AND source change directory SHALL be preserved intact.

### Requirement: Provider execution evidence sufficiency

Provider execution wrappers SHALL verify that process exit code 0 is accompanied by valid, non-empty output artifacts before reporting execution success.

#### Scenario: Provider process exits 0 but expected output evidence is missing
GIVEN an execution provider or auditor process
WHEN the process exits with code 0 but the required output report or patch file is missing or empty
THEN provider runner SHALL return outcome UNKNOWN with reason code EVIDENCE_INSUFFICIENT
AND domain caller SHALL trigger NEEDS_HUMAN gate rather than false completion.

#### Scenario: Provider execution timeout
GIVEN an execution provider invocation
WHEN subprocess timeout expires before process exit
THEN provider runner SHALL terminate process and return outcome UNKNOWN or FAILURE with reason code TIMEOUT
AND SHALL NOT report execution success.

### Requirement: Deployment action success versus production verification truth

Deployment services SHALL explicitly separate deployment execution success (`DEPLOY_ACTION_SUCCESS`) from production reachability and health verification truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).

#### Scenario: Deployment command succeeds but health verification is unreachable
GIVEN a deployment script execution returning exit code 0
WHEN subsequent HTTP health check endpoint query fails or times out
THEN deployment result SHALL report deploy_action_outcome = SUCCESS
AND production_verification SHALL be explicitly UNKNOWN
AND production state SHALL NOT be marked verified.

### Requirement: External action observe-before-repeat idempotency primitive

Mutating external side effects SHALL be recorded in `OrchestrationExternalAction` and SHALL observe external remote state before re-attempting operations following an `AMBIGUOUS` or `UNKNOWN` outcome.

#### Scenario: Repeated external action after ambiguous result
GIVEN a prior external action recorded in state AMBIGUOUS or UNKNOWN
WHEN retry execution is initiated
THEN the system SHALL query external remote state (e.g. PR, issue, or branch existence) before re-issuing side effect
AND IF remote state confirms postcondition, action SHALL transition to COMPLETED without duplicate execution.

### Requirement: Fail-closed caller contract and PostMerge re-observation

Domain callers (`PostMergeService`, `ReadinessService`, `IntakeService`, `OrchestrationService`) SHALL consume typed `ExternalActionResult[T]` outcomes, fail closed on non-SUCCESS results, and re-observe external truth on repeated invocations without fabricating phase completions.

#### Scenario: PostMergeService repeated invocation re-observes external evidence
GIVEN PostMergeService executing post-merge reconciliation
WHEN invoked for a run or change
THEN it SHALL query actual remote GitHub issue, PR, and Git ref status via GitHubAdapter
AND SHALL NOT return all phase booleans = True when remote evidence is unobserved or failed.
