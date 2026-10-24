## Purpose
Keep onboarding data minimal and truthful, preserve existing project and repository evidence through migration, and recover safely from interrupted Git, agent, and GitHub operations.

## ADDED Requirements

### Requirement: Persist only configuration and minimum onboarding continuity
PostgreSQL SHALL remain the authority for project configuration, explicit profiles/policy and the minimum bootstrap identity needed to resume or observe the current PR (project, operation revision, repository, branch, base/head SHA, PR id/url and status). It SHALL NOT become a local ticket backlog, duplicate PR history, archive of ZIP bytes, or generalized workflow/saga queue. GitHub Issues, Git branches/commits, PRs and merges remain authoritative in their respective systems.

#### Scenario: Project has pending bootstrap PR
- **WHEN** a bootstrap candidate is published
- **THEN** the minimum exact branch/base/head/PR identity is durably stored so restart can query the same remote operation

#### Scenario: Project credentials or ZIP are persisted
- **WHEN** project configuration or onboarding progress is read from PostgreSQL
- **THEN** it contains only credential references and package provenance/hash needed for continuity, not private key bytes or a duplicate ZIP archive

### Requirement: Alembic migration preserves useful existing projects and is reversible
F2 schema changes SHALL be made through a new Alembic revision from the actual repository head. Existing project ids, repository identities, branch/bindings, auth, budget, candidate, worktree and audit evidence with live consumers SHALL remain readable. Backfills SHALL not infer roles or `PREPARED` status without evidence. Destructive field removal SHALL occur only after consumer/FK/data census and a verified backup/restore and upgrade/downgrade on disposable PostgreSQL with representative legacy and new rows.

#### Scenario: Upgrade existing project data
- **WHEN** an upgrade is run against representative existing project/binding/auth/evidence rows
- **THEN** identities and retained information remain readable under the new model and historical Alembic files are unchanged

#### Scenario: Unmappable legacy project roles
- **WHEN** an existing row lacks verifiable settings for one or more new roles
- **THEN** the project is marked configured/blocked pending explicit operator configuration, not assigned fabricated roles or marked prepared

#### Scenario: Downgrade after F2 schema upgrade
- **WHEN** a test database is downgraded and restored from the protected backup
- **THEN** retained pre-F2 project information is restored/readable and any intentionally nonrepresentable new data is reported without silent deletion

### Requirement: Preserve and explicitly reconcile the two historical project registrations
The F2 migration SHALL recognize only the two existing registered projects identified in Issue #170 section J (currently `mini-me` / `silverberdi/mini-me` and `mini-me-fixture` / `silverberdi/mini-me-r01-e2e-20261014`) by verifying real persisted identities, managed repository bindings and context evidence before writes. It SHALL migrate their verified configuration without replacing or duplicating project rows, worktrees, Git evidence or existing approved OpenSpec context. For these historical rows alone, readiness MAY be established from verifiable preexisting authorized OpenSpec/project/context/capability evidence rather than demanding a retroactive new GREENFIELD ZIP/bootstrap PR. A legacy READY field alone SHALL NOT prove readiness. Missing required roles/capabilities/credentials SHALL be surfaced as concrete CONFIGURED/BLOCKED reasons without fabricating defaults. This narrowly scoped migration SHALL NOT enable generalized BROWNFIELD onboarding.

#### Scenario: Existing mini me project remains usable for later self-development
- **GIVEN** the real `mini-me` row and bound `silverberdi/mini-me` managed repository with historical OpenSpec/context
- **WHEN** F2 migrates the row and verifies identity, configured capabilities, existing authorized context and credentials
- **THEN** it preserves the same project id/binding and eligible readiness for F3 to run F5/F6 without requiring a fabricated ZIP or first-bootstrap PR
- **AND** any genuinely missing configuration is explicitly reported rather than guessed

#### Scenario: Existing E2E fixture remains isolated
- **GIVEN** the real `mini-me-fixture` row bound to `silverberdi/mini-me-r01-e2e-20261014`
- **WHEN** F2 migrates provider connections, roles and onboarding state
- **THEN** it preserves that fixture's original repo/workspace/bindings/test evidence and does not borrow the main project's credentials, profiles or context

#### Scenario: Historical inventory does not match actual data
- **WHEN** either persisted id/repo/binding differs from the historical inventory or no verifiable readiness evidence exists
- **THEN** only the affected reconciliation is blocked with observable discrepancies; the system SHALL NOT rewrite identity, invent approval, add a duplicate project or mark it PREPARED

#### Scenario: New Brownfield project is not silently grandfathered
- **WHEN** a newly registered BROWNFIELD project is created after F2
- **THEN** historical migration exceptions cannot make it PREPARED without the future explicitly authorized adaptation flow

### Requirement: Resume or block an interrupted operation without repeating side effects
On restart/retry, mini me SHALL query the bound workspace/GitHub branch/commit/PR using the selected project's credential before repeating clone, branch, commit, push, agent invocation, or PR creation. Exact existing effects SHALL be reused; unknown outcomes or mismatched repository/base/head SHALL be retained and blocked for reconciliation. Paid agent work SHALL not be blindly repeated and no retry is unbounded.

#### Scenario: Restart after PR creation response is lost
- **WHEN** provider response is ambiguous after creating a PR
- **THEN** mini me finds and binds the matching base/head PR or marks the operation blocked; it does not create a second PR

#### Scenario: Restart after agent interruption
- **WHEN** agent execution stops after making workspace changes but before a reported result
- **THEN** mini me preserves and inspects the bound diff/checkpoint before any further agent charge; it does not discard work or replay blindly

#### Scenario: Repository identity changes
- **WHEN** remote origin, project binding, branch base, PR head, or managed root differs from the durable identity
- **THEN** all write/dispatch operations stop and the project remains blocked until an authorized reconciliation

### Requirement: Expose minimal usable API and CLI without starting F3
Authenticated API and CLI SHALL support project registration, list/read/edit, activation/pause, Greenfield bootstrap and incremental context submission/status. They SHALL use the same validated project service, report truthful state, and MUST NOT activate ticket selection, dispatch F3 lifecycle work, or start a scheduler. The API SHALL keep every mutating project operation behind the existing authentication/authorization boundary.

#### Scenario: Unauthenticated mutation
- **WHEN** a request without an authorized operator attempts project creation, edit, activation, pause, bootstrap, or context update
- **THEN** authentication rejects it before DB or external mutation

#### Scenario: Activate prepared project in F2
- **WHEN** an operator activates a Greenfield project after confirmed bootstrap merge or activates a Brownfield configuration
- **THEN** lifecycle status is updated but no Issue is selected, no agent runs and no scheduler starts

#### Scenario: CLI operation fails validation
- **WHEN** a CLI command omits required project fields or selects incompatible capabilities
- **THEN** it returns non-zero with a clear sanitized reason and makes no protected side effect
