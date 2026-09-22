# Fail-Closed External Evidence and Actions Specification

## Purpose

Provides a unified, strongly typed outcome model and fail-closed postcondition verification for all external side effects and observations across GitHub, Git, OpenSpec, execution providers, and deployment services, guaranteeing that unobserved or ambiguous outcomes never advance execution state.

## Requirements

### Requirement: Strongly typed external outcome model and fail-closed retry safety

The system SHALL represent all external adapter queries and mutating side effects using a strongly typed container (`ExternalActionResult[T]`) with explicit outcome states (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`), strictly typed reason codes (`reason_code: ExternalReasonCode`), optional provider details (`provider_detail`), required source adapter identity, and explicit fail-closed retry safety (`RetrySafety.SAFE`, `UNSAFE`, `UNKNOWN`).

#### Scenario: Successful read query returns SUCCESS with observed data and SAFE retry
GIVEN a valid read-only external query (e.g. GET repository, GET issue, ls-remote)
WHEN the remote system returns an authoritative positive response
THEN the adapter SHALL return outcome SUCCESS
AND reason_code SHALL be EXECUTION_SUCCESS
AND retry_safety SHALL be marked SAFE (query is read-only and idempotent).

#### Scenario: Successful mutating action returns SUCCESS with UNSAFE retry safety
GIVEN a mutating external side effect (e.g. POST issue, POST PR, PATCH close issue, DELETE branch)
WHEN the remote system confirms successful execution of the side effect
THEN the adapter SHALL return outcome SUCCESS
AND reason_code SHALL be EXECUTION_SUCCESS or ALREADY_*
AND retry_safety SHALL be marked UNSAFE (re-executing the mutating action is forbidden)
AND duplicate side effects SHALL be prevented by operation_key, historical COMPLETED action records, and reconciliation.

#### Scenario: Read-only GET query timeout returns UNKNOWN with SAFE retry
GIVEN a read-only query to inspect remote external state
WHEN network timeout occurs before response receipt
THEN the adapter SHALL return outcome UNKNOWN
AND reason_code SHALL be TIMEOUT
AND retry_safety SHALL be marked SAFE (repeating the read query is safe).

#### Scenario: Mutating request timeout after transmission returns AMBIGUOUS with UNKNOWN retry safety
GIVEN a mutating POST, PATCH, or DELETE request sent to an external API
WHEN network timeout occurs after request transmission
THEN the adapter SHALL return outcome AMBIGUOUS
AND reason_code SHALL be TIMEOUT
AND retry_safety SHALL be marked UNKNOWN (fails closed against automatic re-transmission).

### Requirement: Strictly typed reason codes without string fallbacks

The `reason_code` field on `ExternalActionResult[T]` SHALL be restricted strictly to the `ExternalReasonCode` enum taxonomy, and optional provider-specific raw errors SHALL be carried in `provider_detail`.

#### Scenario: Adapter populates strictly typed ExternalReasonCode
GIVEN an adapter creating an ExternalActionResult
WHEN the operation completes, fails, or times out
THEN reason_code SHALL be set strictly to an ExternalReasonCode enum value
AND raw HTTP status or CLI error output MAY be placed in provider_detail
AND free-form string assignment to reason_code SHALL be forbidden.

### Requirement: Elimination of fabricated default success in production adapters

Production adapters SHALL NOT return synthetic identifiers (e.g. `issue #1`, `PVTI_mock_*`), dummy URLs, default `True` boolean returns on exceptions, or implied default parameters (`source_adapter` and `reason_code` must be explicitly provided).

#### Scenario: Adapter method unavailable or unimplemented
GIVEN an external adapter method or provider interface
WHEN the underlying service or binary is unavailable or unimplemented
THEN the adapter SHALL return outcome FAILURE or UNKNOWN
AND reason_code SHALL be UNSUPPORTED
AND retry_safety SHALL be marked UNSAFE
AND SHALL NOT return synthetic data or default True.

### Requirement: Fail-closed GitHub Project item lookup and binding

GitHub Project V2 item lookups, additions, and status edits SHALL execute fail-closed postcondition verification and return typed outcome reports without fabricating project item IDs.

#### Scenario: Authoritative project item absence on read query
GIVEN valid repository/project identity and authorization
WHEN project item lookup authoritatively confirms no item is bound to the requested issue or resource
THEN the adapter SHALL return outcome FAILURE
AND reason_code SHALL be NOT_FOUND
AND retry_safety SHALL be marked SAFE (query)
AND no synthetic project item ID (such as PVTI_mock_*) SHALL be returned.

#### Scenario: Confirmed authorization rejection on project item read query
GIVEN a query to inspect GitHub Project item state
WHEN gh CLI or REST API returns HTTP 401 or 403 authorization rejection
THEN the adapter SHALL return outcome FAILURE
AND reason_code SHALL be AUTH_REQUIRED
AND retry_safety SHALL be marked SAFE (for the read query itself)
AND no synthetic project item ID SHALL be returned.

#### Scenario: Unobservable project item read query
GIVEN a query to inspect GitHub Project item state
WHEN gh CLI or REST API encounters network timeout, HTTP 429 rate limit, or transport failure
THEN the adapter SHALL return outcome UNKNOWN
AND reason_code SHALL be TIMEOUT, RATE_LIMITED, or UNOBSERVABLE as evidence dictates
AND retry_safety SHALL be marked SAFE (query)
AND no synthetic project item ID SHALL be returned.

#### Scenario: Mutating project item addition CLI failure or timeout after request send
GIVEN a request to add an issue to a GitHub Project V2 via gh project item-add
WHEN gh CLI execution times out, loses connection, or exits abnormally after command transmission
THEN the adapter SHALL return outcome AMBIGUOUS
AND reason_code SHALL be TIMEOUT or UNOBSERVABLE
AND retry_safety SHALL be marked UNKNOWN (fails closed against blind repeat)
AND no synthetic project item ID SHALL be returned.

#### Scenario: Existing project item lookup
GIVEN an existing project item authoritatively observed and correlated to the intended issue
THEN the adapter SHALL return outcome SUCCESS
AND reason_code SHALL be REUSED_EXISTING or EXECUTION_SUCCESS
AND data SHALL contain the real observed project item ID.

### Requirement: Stable operation identity and marker-based issue deduplication

Mutating external operations SHALL generate a deterministic `operation_key` bound to project identity, action type, target item key, and generation metadata, and MUST NOT rely on title-only matching for resource deduplication.

#### Scenario: GitHub create_issue deduplication uses exact operation key comment marker
GIVEN a request to create a GitHub Issue with title T and operation_key K
WHEN pre-creation lookup inspects remote issues in repository R
THEN issue reuse (SUCCESS with reason_code REUSED_EXISTING and retry_safety UNSAFE) SHALL be authorized ONLY if an existing issue body contains the exact marker comment `<!-- minime-opkey: K -->`
AND existing issues with title T lacking exact marker K SHALL NOT be reused.

#### Scenario: GitHub create_issue timeout after POST request transmission
GIVEN a request to create a GitHub Issue with operation_key K
WHEN network timeout occurs after POST request transmission
THEN GitHubAdapter SHALL return outcome AMBIGUOUS with reason_code TIMEOUT and retry_safety UNKNOWN
AND SHALL NOT return synthetic issue #1 or fake HTML URL.

#### Scenario: GitHub create_issue hard 401/403 authorization error
GIVEN a request to create a GitHub Issue
WHEN GitHub API returns HTTP 401 or 403 authorization failure
THEN GitHubAdapter SHALL return outcome FAILURE with reason_code AUTH_REQUIRED and retry_safety UNSAFE
AND SHALL NOT retry or fabricate success.

#### Scenario: GitHub close_issue encounters 404 or unobservable issue
GIVEN a request to close a GitHub Issue
WHEN GET issue query returns HTTP 404 Not Found or HTTP 500 error
THEN GitHubAdapter SHALL return outcome FAILURE with reason_code NOT_FOUND (if 404) or UNKNOWN with reason_code UNOBSERVABLE (if 500)
AND SHALL NOT return boolean True on exception.

#### Scenario: GitHub close_issue on already-closed issue
GIVEN a request to close a GitHub Issue
WHEN GET issue check observes issue state == "closed"
THEN GitHubAdapter SHALL return outcome SUCCESS with reason_code ALREADY_CLOSED and retry_safety UNSAFE
AND SHALL NOT issue duplicate PATCH requests.

#### Scenario: Re-use of existing Pull Request
GIVEN a request to create a Pull Request for head branch B and base branch M
WHEN remote lookup observes an existing PR bound to head branch B, base branch M, and candidate SHA S
THEN GitHubAdapter SHALL return outcome SUCCESS with data set to existing PR details, reason_code REUSED_EXISTING, and retry_safety UNSAFE
AND SHALL NOT attempt duplicate PR creation.

### Requirement: Fail-closed Git operations and branch deletion logic

Git operations for ancestry, branch push, ls-remote, worktree cleanup, and branch deletion SHALL verify explicit return codes, stderr/stdout messages, and exact ref evidence, and MUST NOT treat HTTP 404 alone as unconditional success.

#### Scenario: Git ancestry verification fails or cannot be established
GIVEN a candidate commit SHA and base reference
WHEN git merge-base --is-ancestor fails or encounters a missing/corrupted git reference
THEN ancestry verification SHALL return outcome UNKNOWN with reason_code UNOBSERVABLE
AND SHALL NOT report merged or valid ancestry.

#### Scenario: Remote branch deletion on already-absent branch with authoritative ref observation
GIVEN a request to delete a remote Git branch B in repository R
WHEN remote DELETE returns 404 AND subsequent ls-remote query under valid authorization confirms refs/heads/B is absent in repository R
THEN GitHubAdapter SHALL return outcome SUCCESS with reason_code ALREADY_ABSENT and retry_safety UNSAFE
AND SHALL NOT attempt duplicate mutation.

#### Scenario: Remote branch deletion 404 without authoritative ref observation
GIVEN a request to delete a remote Git branch B
WHEN DELETE API or GET query returns 404 BUT repository authorization or ref identity cannot be authoritatively established
THEN GitHubAdapter SHALL return outcome UNKNOWN with reason_code UNOBSERVABLE and retry_safety UNKNOWN
AND SHALL NOT return outcome SUCCESS.

### Requirement: Response payload malformation classification

Malformed external responses SHALL be classified deterministically as `UNKNOWN` for read queries and `AMBIGUOUS` for mutating side effects.

#### Scenario: Malformed read query response returns UNKNOWN
GIVEN a read-only GET query to GitHub API or Git utility
WHEN response payload is malformed or unparseable JSON
THEN the adapter SHALL return outcome UNKNOWN with reason_code MALFORMED_RESPONSE and retry_safety SAFE.

#### Scenario: Malformed response after mutating request returns AMBIGUOUS
GIVEN a mutating POST, PATCH, or DELETE request sent to external API
WHEN response payload is malformed or unparseable JSON after request acceptance
THEN the adapter SHALL return outcome AMBIGUOUS with reason_code MALFORMED_RESPONSE and retry_safety UNKNOWN.

### Requirement: OpenSpec and filesystem action postcondition verification

OpenSpec canonical spec sync and active change archiving SHALL confirm verifiable filesystem postconditions before reporting success.

#### Scenario: OpenSpec sync command succeeds but canonical spec missing
GIVEN an OpenSpec sync command execution returning exit code 0
WHEN target spec.md is missing on disk or lacks a valid Requirements section
THEN sync verification SHALL return outcome FAILURE with reason_code POSTCONDITION_NOT_PROVEN
AND SHALL NOT report sync success.

#### Scenario: Archive directory move partially completes
GIVEN a request to archive an OpenSpec change
WHEN directory relocation fails before full directory migration
THEN archive operation SHALL return outcome AMBIGUOUS with reason_code TIMEOUT or UNOBSERVABLE and retry_safety UNKNOWN
AND source change directory SHALL be preserved intact.

### Requirement: Provider execution evidence sufficiency

Provider execution wrappers SHALL verify that process exit code 0 is accompanied by valid, non-empty output artifacts before reporting execution success.

#### Scenario: Provider process exits 0 but expected output evidence is missing
GIVEN an execution provider or auditor process
WHEN the process exits with code 0 BUT the required output report or patch file is missing or empty
THEN provider runner SHALL return outcome UNKNOWN with reason_code EVIDENCE_INSUFFICIENT and retry_safety UNSAFE
AND domain caller SHALL trigger NEEDS_HUMAN gate rather than false completion.

#### Scenario: Provider execution timeout
GIVEN an execution provider invocation
WHEN subprocess timeout expires before process exit
THEN provider runner SHALL terminate process and return outcome UNKNOWN with reason_code TIMEOUT and retry_safety UNSAFE
AND SHALL NOT report execution success.

### Requirement: Deployment action success versus production verification truth

Deployment services SHALL explicitly separate deployment execution success (`DEPLOY_ACTION_SUCCESS`) from production reachability and health verification truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).

#### Scenario: Deployment command succeeds but health verification is unreachable
GIVEN a deployment script execution returning exit code 0
WHEN subsequent HTTP health check endpoint query fails or times out
THEN deployment result SHALL report deploy_action_outcome = SUCCESS with reason_code EXECUTION_SUCCESS and retry_safety UNSAFE
AND production_verification SHALL be explicitly UNKNOWN with reason_code POSTCONDITION_NOT_PROVEN
AND production state SHALL NOT be marked verified.

### Requirement: Observe-before-repeat idempotency protocol

When an external action record is in state `AMBIGUOUS`, retrying or repeating the operation SHALL follow an authoritative 5-step protocol and MUST NOT treat absence alone as safe to retry.

#### Scenario: Ambiguous action followed by UNKNOWN reconciliation prevents automatic repeat
GIVEN a prior external action recorded in state AMBIGUOUS
WHEN observe-before-repeat reconciliation runs AND remote query returns UNKNOWN
THEN the system SHALL NOT retry the mutating action automatically
AND action status SHALL remain AMBIGUOUS with retry_safety UNKNOWN.

#### Scenario: Ambiguous action followed by authoritative proof of non-execution authorizes retry ONLY if SAFE
GIVEN a prior external action recorded in state AMBIGUOUS
WHEN observe-before-repeat reconciliation authoritatively proves the remote effect did NOT occur
THEN retry MAY be authorized ONLY IF retry_safety is explicitly SAFE
AND IF retry_safety is UNKNOWN or UNSAFE, automatic retry SHALL be strictly BLOCKED.

### Requirement: Distinction between historical action evidence and current remote truth

Stored `COMPLETED` action records in `OrchestrationExternalAction` SHALL record historical execution evidence to prevent duplicate side effects, but MUST NOT substitute for current-state remote observation when a caller requires current remote truth.

#### Scenario: PostMergeService repeated invocation re-observes current external state
GIVEN PostMergeService executing post-merge reconciliation for a change
WHEN reconciliation evaluates required closure postconditions (issue closure, branch absence, sync spec presence)
THEN it SHALL query current remote external truth via GitHubAdapter and Git utilities
AND SHALL NOT return all phase booleans = True when remote evidence is unobserved, failed, or absent
AND stored COMPLETED action records SHALL prevent duplicate mutation commands without fabricating current-state observation.
