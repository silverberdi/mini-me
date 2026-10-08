# Autonomous Work Discovery Specification

## Purpose
Discover, match, and reconcile candidate backlog items from the canonical GitHub Project (#2) with registered repositories and OpenSpec changes.

## Requirements

### Requirement: Registered Repository Work Discovery
The system SHALL periodically and on-demand discover backlog and issue items from the canonical GitHub Project (#2) for all registered repositories in `uow.projects`, extracting associated OpenSpec change identities without presentation layers selecting execution repositories.

#### Scenario: Discover valid backlog item for registered repository
- **GIVEN** a registered project `mini-me` bound to repository `silverberdi/mini-me`
- **AND** an open issue `#45` in `silverberdi/mini-me` linked to OpenSpec change `016-autonomous-queue-work-selection`
- **WHEN** `WorkDiscoveryService.discover_work()` executes
- **THEN** the system SHALL discover issue `#45`
- **AND** create or update a corresponding `WorkQueueItem` record for `mini-me` and change `016-autonomous-queue-work-selection`.

#### Scenario: Ignore items for unregistered repositories
- **GIVEN** an issue in GitHub Project #2 belonging to repository `other-owner/unregistered-repo`
- **WHEN** `WorkDiscoveryService.discover_work()` executes
- **THEN** the system SHALL ignore the item and NOT persist it to the work queue.

### Requirement: Durable Binding Reconciliation
The system SHALL reconcile discovered work items with `ProjectBinding`, creating durable bindings when valid matching OpenSpec change directories exist and validating issue numbers and repository bindings.

#### Scenario: Automatically reconcile missing durable binding
- **GIVEN** a discovered GitHub issue `#46` for registered project `mini-me`
- **AND** a valid OpenSpec change directory exists at `openspec/changes/017-pwa-control-center`
- **AND** no `ProjectBinding` currently exists for that change
- **WHEN** discovery reconciliation executes
- **THEN** the system SHALL create a durable `ProjectBinding` record linking `project_id="mini-me"`, `openspec_change_name="017-pwa-control-center"`, and `github_issue_number=46`.

### Requirement: Discovery Idempotency and Restart Safety
The system SHALL ensure discovery execution is completely idempotent, updating queue state and metadata without creating duplicate queue items, corrupting bindings, or modifying immutable execution history.

#### Scenario: Repeated discovery execution produces identical state
- **GIVEN** an already discovered work item for change `016-autonomous-queue-work-selection`
- **WHEN** `WorkDiscoveryService.discover_work()` is invoked multiple times in succession
- **THEN** the system SHALL retain exactly one `WorkQueueItem` record
- **AND** the record's `last_evaluated_at` SHALL reflect the latest evaluation timestamp without modifying `discovered_at`.

### Requirement: Context Discovery Deterministic Deduplication
`ContextDiscoveryService.discover_context_pure(project_id)` SHALL return at most one discovered `BacklogItem` projection for each `(project_id, item_key)` tuple prior to persistence, deterministically selecting the highest precedence state when duplicate evidence appears across canonical sources.

#### Scenario: Duplicate milestone key in ROADMAP produces single discovered projection
- **GIVEN** a canonical `ROADMAP.md` containing multiple sections referencing the same item key `019-server-runtime-deployment`
- **WHEN** `discover_context_pure("mini-me")` is invoked
- **THEN** it SHALL return exactly one `BacklogItem` with `item_key="019-server-runtime-deployment"`
- **AND** the returned item SHALL reflect the highest precedence status (e.g. `COMPLETED` over `BACKLOG`)
- **AND** `discover_context("mini-me")` SHALL persist exactly one row without violating `uq_backlog_items_project_key`.

#### Scenario: Repeated context discovery execution is idempotent
- **GIVEN** a project with duplicate context evidence in `ROADMAP.md`
- **WHEN** `discover_context("mini-me")` is executed multiple times in succession
- **THEN** it SHALL succeed without raising `IntegrityError`
- **AND** exactly one `BacklogItem` row per `(project_id, item_key)` SHALL exist in persistence
- **AND** existing persisted terminal state SHALL not be resurrected or mutated
- **AND** context discovery SHALL NOT directly advance existing persisted non-terminal lifecycle status.
