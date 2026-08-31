# Autonomous Work Discovery Specification

## ADDED Requirements

### Requirement: Registered Repository Work Discovery
The system SHALL periodically and on-demand discover backlog and issue items from the canonical GitHub Project (#2) for all registered repositories in `uow.projects`, extracting associated OpenSpec change identities without presentation layers selecting execution repositories.

#### Scenario: Discover valid backlog item for registered repository
Given a registered project `mini-me` bound to repository `silverberdi/mini-me`
And an open issue `#45` in `silverberdi/mini-me` linked to OpenSpec change `016-autonomous-queue-work-selection`
When `WorkDiscoveryService.discover_work()` executes
Then the system SHALL discover issue `#45`
And create or update a corresponding `WorkQueueItem` record for `mini-me` and change `016-autonomous-queue-work-selection`.

#### Scenario: Ignore items for unregistered repositories
Given an issue in GitHub Project #2 belonging to repository `other-owner/unregistered-repo`
When `WorkDiscoveryService.discover_work()` executes
Then the system SHALL ignore the item and NOT persist it to the work queue.

### Requirement: Durable Binding Reconciliation
The system SHALL reconcile discovered work items with `ProjectBinding`, creating durable bindings when valid matching OpenSpec change directories exist and validating issue numbers and repository bindings.

#### Scenario: Automatically reconcile missing durable binding
Given a discovered GitHub issue `#46` for registered project `mini-me`
And a valid OpenSpec change directory exists at `openspec/changes/017-pwa-control-center`
And no `ProjectBinding` currently exists for that change
When discovery reconciliation executes
Then the system SHALL create a durable `ProjectBinding` record linking `project_id="mini-me"`, `openspec_change_name="017-pwa-control-center"`, and `github_issue_number=46`.

### Requirement: Discovery Idempotency and Restart Safety
The system SHALL ensure discovery execution is completely idempotent, updating queue state and metadata without creating duplicate queue items, corrupting bindings, or modifying immutable execution history.

#### Scenario: Repeated discovery execution produces identical state
Given an already discovered work item for change `016-autonomous-queue-work-selection`
When `WorkDiscoveryService.discover_work()` is invoked multiple times in succession
Then the system SHALL retain exactly one `WorkQueueItem` record
And the record's `last_evaluated_at` SHALL reflect the latest evaluation timestamp without modifying `discovered_at`.
