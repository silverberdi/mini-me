# Spec Delta

## Purpose

Define the observable F12 contract for removing unreachable legacy code, obsolete tests and durable state while preserving the active Angular/API/operator capabilities and proving real post-retirement behavior.

## ADDED Requirements

### Requirement: F12 retires only proven-obsolete surfaces
F12 SHALL remove a target only after static reachability, configuration, dependency and applicable runtime evidence show no legitimate active or historical consumer, and SHALL classify each inspected target as REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON.

#### Scenario: Orphaned target is removed
- **WHEN** a TUI, legacy endpoint, emulator, test, dependency or repository has no legitimate consumer and its replacement remains active
- **THEN** F12 SHALL remove the target and exclusive callers/tests/configuration in the same Change
- **AND** retained behavior SHALL be exercised again after removal.

#### Scenario: Durable or active dependency remains
- **WHEN** an item is consumed by an active flow, audit record, candidate/worktree, applied migration or historical obligation
- **THEN** F12 SHALL retain or migrate it with an explicit reason
- **AND** SHALL NOT delete it solely because it appears unused by text search.

### Requirement: Active operational capabilities remain available
 F12 SHALL preserve the active Angular routes `/`, `/dashboard`, `/trabajo`, `/trabajo-actual`, `/proyectos` and `/backlog` (with the wildcard redirected to `/dashboard`), and the active FastAPI contracts `/api/v1/projects`, `/api/v1/projects/{project_id}/requests`, `/health`, `/status`, `/scheduler/status`, `/providers/health`, `/budget/usage`, `/projects/{project_id}/budget` and `/api/v1/auth/me`; it SHALL also preserve Angular production static assets, native orchestration, CLI runners, worktree management, GitHub and configured agent adapters, and operator authentication/authorization.

#### Scenario: Retained API and adapters remain functional
- **WHEN** the post-retirement functional journey invokes retained API and coordination paths
- **THEN** the interfaces SHALL return their expected observable results and side effects
- **AND** the evidence SHALL identify the immutable candidate SHA.

### Requirement: Retained tests prove behavior rather than synthetic coverage
Tests retained by F12 SHALL validate active contracts and observable behavior, while mocks SHALL be limited to isolated unit/contract boundaries and SHALL NOT be reported as real integration or E2E evidence.

#### Scenario: Obsolete test is removed and regression is retained
- **WHEN** a test exists solely for a removed TUI, 410 endpoint, legacy service or artificial signature
- **THEN** it SHALL be removed
- **AND** any still-relevant behavior SHALL be covered by a real applicable test after retirement.

#### Scenario: Real post-retirement suite completes
- **WHEN** the retained test suite and applicable real E2E journey run against the candidate
- **THEN** each retained test SHALL exit successfully
- **AND** missing, simulated or ambiguous integration evidence SHALL fail closed rather than count as completion.

### Requirement: Retired dependencies are absent from active metadata
F12 SHALL remove a dependency that is exclusive to a retired surface from project metadata and applicable lock or installation metadata, while preserving dependencies required by retained capabilities.

#### Scenario: Textual is exclusive to the retired TUI
- **WHEN** the inventory confirms that no retained import, optional extra or installation path requires `textual`
- **THEN** `textual` SHALL be removed from `pyproject.toml` and applicable lock/dependency metadata
- **AND** dependency inspection SHALL prove that the retained installation does not require it.

#### Scenario: Dependency consumer remains ambiguous
- **WHEN** a retained import, optional extra or installation path still requires `textual` or another candidate dependency
- **THEN** the dependency SHALL be classified RETAIN-WITH-REASON
- **AND** F12 SHALL NOT remove it until the consumer is resolved by evidence or an authorized OpenSpec update.
